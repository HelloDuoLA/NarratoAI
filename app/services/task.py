import math
import json
import os.path
import re
import traceback
import streamlit as st
from os import path
from loguru import logger
from datetime import datetime

from app.config import config
from app.config.audio_config import AudioConfig, get_recommended_volumes_for_content
from app.models import const
from app.models.schema import VideoClipParams
from app.services import (voice, audio_merger, subtitle_merger, clip_video, merger_video, update_script, generate_video)
from app.services import state as sm
from app.utils import utils
from .tts_final import perform_speech_recognition
import copy

def start_subclip(task_id: str, params: VideoClipParams, subclip_path_videos: dict):
    """
    后台任务（自动剪辑视频进行剪辑）
    Args:
        task_id: 任务ID
        params: 视频参数
        subclip_path_videos: 视频片段路径
    """
    global merged_audio_path, merged_subtitle_path

    logger.info(f"\n\n## 开始任务: {task_id}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)

    """
    1. 加载剪辑脚本
    """
    logger.info("\n\n## 1. 加载视频脚本")
    video_script_path = path.join(params.video_clip_json_path)
    
    if path.exists(video_script_path):
        try:
            with open(video_script_path, "r", encoding="utf-8") as f:
                list_script = json.load(f)
                video_list = [i['narration'] for i in list_script]
                video_ost = [i['OST'] for i in list_script]
                time_list = [i['timestamp'] for i in list_script]

                video_script = " ".join(video_list)
                logger.debug(f"解说完整脚本: \n{video_script}")
                logger.debug(f"解说 OST 列表: \n{video_ost}")
                logger.debug(f"解说时间戳列表: \n{time_list}")
        except Exception as e:
            logger.error(f"无法读取视频json脚本，请检查脚本格式是否正确")
            raise ValueError("无法读取视频json脚本，请检查脚本格式是否正确")
    else:
        logger.error(f"video_script_path: {video_script_path} \n\n", traceback.format_exc())
        raise ValueError("解说脚本不存在！请检查配置是否正确。")

    """
    2. 使用 TTS 生成音频素材
    """
    logger.info("\n\n## 2. 根据OST设置生成音频列表")
    # 只为OST=0 or 2的判断生成音频， OST=0 仅保留解说 OST=2 保留解说和原声
    tts_segments = [
        segment for segment in list_script 
        if segment['OST'] in [0, 2]
    ]
    logger.debug(f"需要生成TTS的片段数: {len(tts_segments)}")

    tts_results = voice.tts_multiple(
        task_id=task_id,
        list_script=tts_segments,  # 只传入需要TTS的片段
        voice_name=params.voice_name,
        voice_rate=params.voice_rate,
        voice_pitch=params.voice_pitch,
        enable_subtitles=params.subtitle_enabled,
    )

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # """
    # 3. (可选) 使用 whisper 生成字幕
    # """
    # if merged_subtitle_path is None:
    #     if audio_files:
    #         merged_subtitle_path = path.join(utils.task_dir(task_id), f"subtitle.srt")
    #         subtitle_provider = config.app.get("subtitle_provider", "").strip().lower()
    #         logger.info(f"\n\n使用 {subtitle_provider} 生成字幕")
    #
    #         subtitle.create(
    #             audio_file=merged_audio_path,
    #             subtitle_file=merged_subtitle_path,
    #         )
    #         subtitle_lines = subtitle.file_to_subtitles(merged_subtitle_path)
    #         if not subtitle_lines:
    #             logger.warning(f"字幕文件无效: {merged_subtitle_path}")
    #
    # sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

    """
    3. 裁剪视频 - 将超出音频长度的视频进行裁剪 
    """
    # TODO:这么做合理么
    logger.info("\n\n## 3. 裁剪视频")
    video_clip_result = clip_video.clip_video(params.video_origin_path, tts_results) # 这里重新剪辑作用又是什么?是需要额外专门预留一点时间给TTS?
    # 更新 list_script 中的时间戳
    tts_clip_result = {tts_result['_id']: tts_result['audio_file'] for tts_result in tts_results} # 构建一个字典
    subclip_clip_result = {
        tts_result['_id']: tts_result['subtitle_file'] for tts_result in tts_results
    }
    new_script_list = update_script.update_script_timestamps(list_script, video_clip_result, tts_clip_result, subclip_clip_result)

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=60)

    """
    4. 合并音频和字幕
    """
    logger.info("\n\n## 4. 合并音频和字幕")
    total_duration = sum([script["duration"] for script in new_script_list])
    if tts_segments:
        try:
            # 合并音频文件
            # 把TTS合成的音频都填上去了, 为什么不生成TTS的音频不能在这里合呢?
            merged_audio_path = audio_merger.merge_audio_files(
                task_id=task_id,
                total_duration=total_duration,
                list_script=new_script_list
            )
            logger.info(f"音频文件合并成功->{merged_audio_path}")
            # 合并字幕文件
            merged_subtitle_path = subtitle_merger.merge_subtitle_files(new_script_list)
            logger.info(f"字幕文件合并成功->{merged_subtitle_path}")
        except Exception as e:
            logger.error(f"合并音频文件失败: {str(e)}")
    else:
        logger.warning("没有需要合并的音频/字幕")
        merged_audio_path = ""
        merged_subtitle_path = ""

    """
    5. 合并视频
    """
    final_video_paths = []
    combined_video_paths = []

    combined_video_path = path.join(utils.task_dir(task_id), f"merger.mp4")
    logger.info(f"\n\n## 5. 合并视频: => {combined_video_path}")
    # 如果 new_script_list 中没有 video，则使用 subclip_path_videos 中的视频
    # video_clips = [new_script['video'] if new_script.get('video') else subclip_path_videos.get(new_script.get('_id', '')) for new_script in new_script_list]

    video_clips = []
    for new_script in new_script_list:
        if new_script.get('video'):
            video_clips.append(new_script['video'])
        else:
            script_id = new_script.get('_id', '')
            video_path = subclip_path_videos.get(script_id + 1)
            video_clips.append(video_path)
    
    merger_video.combine_clip_videos(
        output_video_path=combined_video_path,
        video_paths=video_clips,
        video_ost_list=video_ost,
        video_aspect=params.video_aspect,
        threads=params.n_threads
    )
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=80)

    """
    6. 合并字幕/BGM/配音/视频
    """
    output_video_path = path.join(utils.task_dir(task_id), f"combined.mp4")
    logger.info(f"\n\n## 6. 最后一步: 合并字幕/BGM/配音/视频 -> {output_video_path}")

    # bgm_path = '/Users/apple/Desktop/home/NarratoAI/resource/songs/bgm.mp3'
    bgm_path = utils.get_bgm_file(st.session_state.get('bgm_type', ''))

    # 获取优化的音量配置
    optimized_volumes = get_recommended_volumes_for_content('mixed')

    # 应用用户设置和优化建议的组合
    # 如果用户设置了非默认值，优先使用用户设置
    final_tts_volume = params.tts_volume if hasattr(params, 'tts_volume') and params.tts_volume != 1.0 else optimized_volumes['tts_volume']
    final_original_volume = params.original_volume if hasattr(params, 'original_volume') and params.original_volume != 0.7 else optimized_volumes['original_volume']
    final_bgm_volume = params.bgm_volume if hasattr(params, 'bgm_volume') and params.bgm_volume != 0.3 else optimized_volumes['bgm_volume']

    logger.info(f"音量配置 - TTS: {final_tts_volume}, 原声: {final_original_volume}, BGM: {final_bgm_volume}")

    # 调用示例
    options = {
        'voice_volume': final_tts_volume,  # 配音音量（优化后）
        'bgm_volume': final_bgm_volume,  # 背景音乐音量（优化后）
        'original_audio_volume': final_original_volume,  # 视频原声音量（优化后）
        'keep_original_audio': True,  # 是否保留原声
        'subtitle_enabled': params.subtitle_enabled,  # 是否启用字幕 - 修复字幕开关bug
        'subtitle_font': params.font_name,  # 这里使用相对字体路径，会自动在 font_dir() 目录下查找
        'subtitle_font_size': params.font_size,
        'subtitle_color': params.text_fore_color,
        'subtitle_bg_color': None,  # 直接使用None表示透明背景
        'subtitle_position': params.subtitle_position,
        'custom_position': params.custom_position,
        'threads': params.n_threads
    }
    generate_video.merge_materials(
        video_path=combined_video_path,
        audio_path=merged_audio_path,
        subtitle_path=merged_subtitle_path,
        bgm_path=bgm_path,
        output_path=output_video_path,
        options=options
    )

    final_video_paths.append(output_video_path)
    combined_video_paths.append(combined_video_path)
    
    '''
    7. 语音识别字幕, 并且进行视频裁剪
    '''
    # TODO:语音识别字幕
    # current_date = datetime.now().strftime("%Y%m%d_%H%M")
    # result = { "final_subtitle_file": None}
    # result = perform_speech_recognition(output_video_path, video_name=f"{current_date}_output_video")

    # logger.success(f"任务 {task_id} 已完成, 生成 {len(final_video_paths)} 个视频.")
    # logger.success(f"视频路径: {final_video_paths[0]}")
    # logger.success(f"字幕路径: {result['final_subtitle_file']}")

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        # "subtitle" : result["final_subtitle_file"]
    }
    sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs)
    return kwargs


def validate_params(video_path, audio_path, output_file, params):
    """
    验证输入参数
    Args:
        video_path: 视频文件路径
        audio_path: 音频文件路径（可以为空字符串）
        output_file: 输出文件路径
        params: 视频参数

    Raises:
        FileNotFoundError: 文件不存在时抛出
        ValueError: 参数无效时抛出
    """
    if not video_path:
        raise ValueError("视频路径不能为空")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")
        
    # 如果提供了音频路径，则验证文件是否存在
    if audio_path and not os.path.exists(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
    if not output_file:
        raise ValueError("输出文件路径不能为空")
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_file)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    if not params:
        raise ValueError("视频参数不能为空")


if __name__ == "__main__":
    task_id = "demo"

    # 提前裁剪是为了方便检查视频
    subclip_path_videos = {
        1: '/Users/apple/Desktop/home/NarratoAI/storage/temp/clip_video/113343d127b5a09d0bf84b68bd1b3b97/vid_00-00-05-390@00-00-57-980.mp4',
        2: '/Users/apple/Desktop/home/NarratoAI/storage/temp/clip_video/113343d127b5a09d0bf84b68bd1b3b97/vid_00-00-28-900@00-00-43-700.mp4',
        3: '/Users/apple/Desktop/home/NarratoAI/storage/temp/clip_video/113343d127b5a09d0bf84b68bd1b3b97/vid_00-01-17-840@00-01-27-600.mp4',
        4: '/Users/apple/Desktop/home/NarratoAI/storage/temp/clip_video/113343d127b5a09d0bf84b68bd1b3b97/vid_00-02-35-460@00-02-52-380.mp4',
        5: '/Users/apple/Desktop/home/NarratoAI/storage/temp/clip_video/113343d127b5a09d0bf84b68bd1b3b97/vid_00-06-59-520@00-07-29-500.mp4',
    }

    params = VideoClipParams(
        video_clip_json_path="/Users/apple/Desktop/home/NarratoAI/resource/scripts/2025-0507-223311.json",
        video_origin_path="/Users/apple/Desktop/home/NarratoAI/resource/videos/merged_video_4938.mp4",
    )
    start_subclip(task_id, params, subclip_path_videos)
