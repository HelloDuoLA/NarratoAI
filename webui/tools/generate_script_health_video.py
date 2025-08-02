# 纪录片脚本生成
# 
import os
import json
import time
import asyncio
import traceback
import streamlit as st
from loguru import logger
from datetime import datetime
import subprocess
import sys
from json_repair import repair_json

from pathlib import Path
import re

from app.config import config
from app.utils import utils, video_processor
from webui.tools.base import create_vision_analyzer, get_batch_files, get_batch_timestamps, check_video_config, create_text_analyzer

# 获取项目根目录
project_root = Path(__file__).parent.parent.parent

def generate_script_health_video(params, subtitle_path, max_concurrent_analysis=None):
    """
    生成 纪录片 视频脚本
    要求: 原视频无字幕无配音
    适合场景: 纪录片、动物搞笑解说、荒野建造等
    
    Args:
        params: 视频处理参数
        subtitle_path: 字幕文件路径
        max_concurrent_analysis: 最大并发分析数量，默认为3
                                可以通过以下方式配置：
                                1. 直接传入参数
                                2. params.max_concurrent_analysis 属性
                                3. 配置文件中的 app.max_concurrent_analysis
                                4. 默认值 3
    """
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(progress: float, message: str = ""):
        progress_bar.progress(progress/100)
        if message:
            status_text.text(f"🎬 {message}")
        else:
            status_text.text(f"📊 进度: {progress}%")

    def srt_to_list(srt_file, *, ensure_ascii=False):
        # 读取完整文本
        text = Path(srt_file).read_text(encoding='utf-8')

        # 用正则提取每一个字幕块
        pattern = re.compile(
            r'(\d+)\s*\n'                    # 序号
            r'(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\s*\n'  # 时间轴
            r'([\s\S]*?)(?=\n\d+\s*\n|\Z)',  # 字幕内容（非贪婪，直到下一个序号或结尾）
            re.MULTILINE
        )

        result = [
            {"timestamp": ts, "subtitle": content.replace('\n', ' ').strip()}
            for _, ts, content in pattern.findall(text)
        ]


        return result
    
    def to_ms(t_str: str) -> int:
        """'HH:MM:SS,mmm' → 毫秒"""
        h, m, s_ms = t_str.split(':')
        s, ms = s_ms.split('.')
        return int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1_000 + int(ms)

    def to_hmsf(ms: int) -> str:
        """毫秒 → 'HH:MM:SS,mmm'"""
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms,   60_000)
        s, ms = divmod(ms,    1_000)
        return f'{h:02d}:{m:02d}:{s:02d}.{int(ms):03d}'


    try:
        with st.spinner("正在生成脚本..."):
            if not params.video_origin_path:
                st.error("请先选择视频文件")
                return
            
            if not subtitle_path:
                st.error("请先选择字幕文件")
                return
            
            
            """
            1. 数据结构构建 - 字幕信息解析
            """
            update_progress(5, "正在解析字幕文件...")
            
            # 将字幕文件转换为列表格式：[{'timestamp': '时间段', 'subtitle': '字幕内容'}, ...]
            video_clips = srt_to_list(subtitle_path)
            
            if not video_clips:
                st.error("字幕文件解析失败或为空，请检查字幕文件格式")
                return
            
            logger.info(f"成功解析字幕文件，共 {len(video_clips)} 条字幕")
            
            
            # 构建字幕与关键帧的映射数据结构
            update_progress(7, "正在构建字幕数据结构...")
            
            subtitle_keyframe_data = []
            
            # 逐个处理字幕片段
            for i, clip in enumerate(video_clips):
                # 更新进度
                current_progress = 7 + (i / len(video_clips)) * 3  # 7%-10%的进度范围
                update_progress(current_progress, f"正在处理第{i+1}/{len(video_clips)}个字幕片段...")
                
                try:
                    # 解析时间戳
                    start_str, end_str = clip['timestamp'].split(' --> ')
                    start_seconds = utils.time_to_seconds(start_str.replace(',', '.'))
                    end_seconds = utils.time_to_seconds(end_str.replace(',', '.'))
                    duration = end_seconds - start_seconds
                    
                    # 构建数据结构
                    data_item = {
                        "index": i,
                        "subtitle_text": clip['subtitle'],
                        "timestamp": clip['timestamp'],  # 保持原始SRT时间戳格式 "00:01:30,500 --> 00:01:35,200"
                        "start_seconds": start_seconds,
                        "end_seconds": end_seconds,
                        "duration": duration,
                        "keyframe_paths": [],  # 存储对应的关键帧路径列表
                        "scene_description": None,  # 稍后通过多模态大模型填充
                    }
                    
                    subtitle_keyframe_data.append(data_item)
                    
                except Exception as e:
                    logger.error(f"处理第{i+1}个片段时出错: {e}")
                    raise RuntimeError(f"处理片段时出错: {e}")
            
            logger.info(f"构建字幕-关键帧映射数据结构完成，共 {len(subtitle_keyframe_data)} 个片段")
            
            """
            2. 提取关键帧并匹配字幕
            """
            update_progress(10, "正在提取关键帧...")

            # 创建临时目录用于存储关键帧
            # !不要放到临时文件夹了，放固定位置
            keyframes_dir = os.path.join(utils.temp_dir(), "keyframes")
            video_hash = utils.md5(params.video_origin_path + str(os.path.getmtime(params.video_origin_path)) + subtitle_path + str(os.path.getmtime(subtitle_path)) +  "health_video")
            video_keyframes_dir = os.path.join(keyframes_dir, video_hash)

            # 检查是否已经提取过关键帧
            keyframe_files = []
            subtitle_keyframe_match_file = os.path.join(video_keyframes_dir, "subtitle_keyframe_match.json")
            logger.info(f"关键帧存储文件夹路径 {video_keyframes_dir}")
            
            if os.path.exists(video_keyframes_dir) and os.path.exists(subtitle_keyframe_match_file):
                # 从缓存的匹配文件中读取数据结构
                try:
                    with open(subtitle_keyframe_match_file, 'r', encoding='utf-8') as f:
                        cached_data = json.load(f)
                    
                    # 获取当前的采样参数
                    current_second_per_frame = config.frames.get('second_per_frame', None)
                    current_max_frames = 10
                    
                    # 检查缓存是否包含采样参数信息（用于验证缓存是否匹配当前参数）
                    cached_sampling_params = cached_data[0].get('sampling_params', {}) if cached_data else {}
                    cached_second_per_frame = cached_sampling_params.get('second_per_frame', None)
                    cached_max_frames = cached_sampling_params.get('max_frames', -1)
                    
                    # 验证缓存数据的完整性和采样参数是否匹配
                    params_match = (cached_second_per_frame == current_second_per_frame and 
                                   cached_max_frames == current_max_frames)
                    
                    if len(cached_data) == len(subtitle_keyframe_data) and params_match:
                        # 更新 subtitle_keyframe_data 使用缓存的关键帧路径
                        for i, cached_item in enumerate(cached_data):
                            if i < len(subtitle_keyframe_data):
                                subtitle_keyframe_data[i]['keyframe_paths'] = cached_item['keyframe_paths']
                        
                        # 统计缓存的关键帧文件
                        total_cached_keyframes = sum(len(item['keyframe_paths']) for item in subtitle_keyframe_data)
                        
                        logger.info(f"使用已缓存的关键帧匹配数据: {subtitle_keyframe_match_file}")
                        st.info(f"✅ 使用已缓存关键帧匹配数据，共 {total_cached_keyframes} 帧")
                        update_progress(20, f"使用已缓存关键帧匹配数据，共 {total_cached_keyframes} 帧")
                        
                        # 标记为使用缓存
                        using_cached_data = True
                    else:
                        if not params_match:
                            logger.warning(f"缓存采样参数不匹配，当前参数: interval={current_second_per_frame}, max_frames={current_max_frames}, 缓存参数: interval={cached_second_per_frame}, max_frames={cached_max_frames}")
                        else:
                            logger.warning(f"缓存数据长度不匹配，重新提取关键帧")
                        using_cached_data = False
                except Exception as cache_error:
                    logger.warning(f"读取缓存匹配数据失败: {cache_error}，重新提取关键帧")
                    using_cached_data = False
            else:
                using_cached_data = False

            # 如果没有缓存的关键帧，则进行提取
            if not using_cached_data:
                try:
                    # 确保目录存在
                    os.makedirs(video_keyframes_dir, exist_ok=True)

                    # 显示视频信息
                    temp_processor = video_processor.VideoProcessor(params.video_origin_path)
                    st.info(f"📹 视频信息: {temp_processor.width}x{temp_processor.height}, {temp_processor.fps:.1f}fps, {temp_processor.duration:.1f}秒")

                    # 提前保存字幕-关键帧匹配数据，供独立工具使用
                    temp_match_file = os.path.join(video_keyframes_dir, "subtitle_keyframe_match_input.json")
                    
                    # 预先生成字幕-关键帧匹配数据，供独立工具使用
                    update_progress(15, "正在准备关键帧提取数据...")
                    
                    # 简化处理：让独立工具负责所有采样逻辑和关键帧路径生成
                    # 主脚本只需要传递字幕片段的基本信息和采样参数
                    
                    with open(temp_match_file, 'w', encoding='utf-8') as f:
                        # 创建一个可序列化的版本（用于独立工具）
                        serializable_data = []
                        for item in subtitle_keyframe_data:
                            serializable_item = {
                                "index": item["index"],
                                "subtitle_text": item["subtitle_text"],
                                "timestamp": item["timestamp"],
                                "start_seconds": item["start_seconds"],
                                "end_seconds": item["end_seconds"],
                                "duration": item["duration"],
                                "keyframe_paths": [],  # 空列表，独立工具会生成实际文件
                                "has_keyframes": False
                            }
                            serializable_data.append(serializable_item)
                        json.dump(serializable_data, f, ensure_ascii=False, indent=2)
                    
                    logger.info(f"字幕-关键帧匹配数据已保存到: {temp_match_file}")

                    # 使用独立的关键帧提取工具
                    update_progress(16, "正在启动独立关键帧提取工具...")
                    
                    # 构建命令行参数
                    # !待验证
                    extract_tool_path = os.path.join(project_root, "tools", "extract_keyframes_simple.py")
                    if not os.path.exists(extract_tool_path):
                        extract_tool_path = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "extract_keyframes_simple.py")
                    
                    # 获取配置参数
                    second_per_frame = config.frames.get('second_per_frame', None)
                    max_frames = 10  # 固定最大帧数为10
                    
                    # 记录采样参数
                    if second_per_frame is not None:
                        logger.info(f"使用采样参数: 间隔 {second_per_frame} 秒提取一帧，最大帧数 {max_frames}")
                    else:
                        logger.info(f"使用默认采样: 每个片段提取中间帧，最大帧数 {max_frames}")
                    
                    cmd = [
                        sys.executable,
                        extract_tool_path,
                        "--video_path", params.video_origin_path,
                        "--subtitle_keyframe_match", temp_match_file,
                        "--output_dir", video_keyframes_dir,
                        "--max_workers", "20",
                        "--log_level", "INFO"
                    ]
                    
                    # 添加新的参数
                    if second_per_frame is not None:
                        cmd.extend(["--interval_seconds", str(second_per_frame)])
                    cmd.extend(["--max_frames", str(max_frames)])
                    
                    logger.info(f"执行命令: {' '.join(cmd)}")
                    
                    # 启动独立进程
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        cwd=os.path.dirname(extract_tool_path) if os.path.exists(os.path.dirname(extract_tool_path)) else None
                    )
                    
                    # 简化的进度监听：直接统计文件数量
                    update_progress(17, "关键帧提取工具已启动，正在监听文件生成...")
                    
                    start_time = time.time()
                    timeout = 3000  # 5分钟超时
                    last_count = 0
                    check_interval = 2  # 每2秒检查一次
                    
                    while True:
                        # 检查进程是否还在运行
                        if process.poll() is not None:
                            # 进程已结束，最后检查一次文件数量
                            break
                        
                        # 检查超时
                        if time.time() - start_time > timeout:
                            logger.error("关键帧提取超时")
                            process.terminate()
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                            raise Exception("关键帧提取超时，请检查视频文件或减少提取数量")
                        
                        # 统计已生成的关键帧文件数量
                        try:
                            if os.path.exists(video_keyframes_dir):
                                # 只统计实际的关键帧文件（.jpg且包含segment_和keyframe_）
                                all_files = os.listdir(video_keyframes_dir)
                                keyframe_files = [
                                    f for f in all_files 
                                    if f.endswith('.jpg') and 'segment_' in f and 'keyframe_' in f
                                ]
                                current_count = len(keyframe_files)
                                
                                if current_count != last_count:
                                    # 简化进度显示，不计算百分比
                                    update_progress(17 + min(current_count * 0.1, 3), f"已提取 {current_count} 个关键帧")
                                    last_count = current_count
                                    
                                    logger.debug(f"当前已提取 {current_count} 个关键帧")
                        
                        except Exception as e:
                            logger.warning(f"统计关键帧文件失败: {e}")
                        
                        # 等待一段时间再检查
                        time.sleep(check_interval)
                    
                    # 等待进程完成
                    stdout, stderr = process.communicate(timeout=30)
                    
                    if process.returncode != 0:
                        logger.error(f"关键帧提取进程失败，返回码: {process.returncode}")
                        logger.error(f"错误输出: {stderr}")
                        raise Exception(f"关键帧提取失败: {stderr}")
                    
                    logger.info("关键帧提取进程完成")
                    
                    # 通过文件名模式匹配重建关键帧数据结构
                    def match_keyframes_by_filename():
                        """
                        通过文件名模式匹配关键帧文件到对应的字幕片段
                        文件名格式: segment_{segment_num}_keyframe_{frame_num}_{timestamp}.jpg
                        """
                        import re
                        import glob
                        
                        # 获取所有关键帧文件
                        keyframe_pattern = os.path.join(video_keyframes_dir, "segment_*_keyframe_*.jpg")
                        keyframe_files = glob.glob(keyframe_pattern)
                        
                        logger.info(f"找到 {len(keyframe_files)} 个关键帧文件")
                        
                        # 先清空所有片段的关键帧路径
                        for data_item in subtitle_keyframe_data:
                            data_item['keyframe_paths'] = []
                        
                        # 解析文件名模式: segment_{segment_num}_keyframe_{frame_num}_{timestamp}.jpg
                        filename_pattern = r'segment_(\d+)_keyframe_(\d+)_(\d+)\.jpg'
                        
                        # 按片段分组关键帧文件
                        segment_keyframes = {}
                        
                        for keyframe_file in keyframe_files:
                            filename = os.path.basename(keyframe_file)
                            match = re.match(filename_pattern, filename)
                            
                            if match:
                                segment_num = int(match.group(1))  # 片段号（从1开始）
                                frame_num = int(match.group(2))    # 帧号（从1开始）
                                timestamp_str = match.group(3)     # 时间戳字符串
                                
                                # 转换为0索引的片段索引
                                segment_index = segment_num - 1
                                
                                if segment_index not in segment_keyframes:
                                    segment_keyframes[segment_index] = []
                                
                                segment_keyframes[segment_index].append({
                                    'path': keyframe_file,
                                    'frame_num': frame_num,
                                    'timestamp_str': timestamp_str,
                                    'filename': filename
                                })
                                
                                logger.debug(f"匹配文件: {filename} -> 片段{segment_index+1}, 帧{frame_num}")
                            else:
                                logger.warning(f"无法解析关键帧文件名: {filename}")
                        
                        # 为每个片段按时间戳排序关键帧并分配到数据结构
                        successful_extractions = 0
                        for segment_index, keyframes in segment_keyframes.items():
                            if segment_index < len(subtitle_keyframe_data):
                                # 按时间戳字符串排序（数字排序）
                                keyframes.sort(key=lambda x: int(x['timestamp_str']))
                                
                                # 提取排序后的文件路径
                                keyframe_paths = [kf['path'] for kf in keyframes]
                                subtitle_keyframe_data[segment_index]['keyframe_paths'] = keyframe_paths
                                
                                successful_extractions += len(keyframe_paths)
                                
                                logger.info(f"片段 {segment_index+1}: 分配 {len(keyframe_paths)} 个关键帧")
                                for kf in keyframes:
                                    logger.debug(f"  -> {kf['filename']}")
                            else:
                                logger.warning(f"片段索引 {segment_index} 超出范围")
                        
                        return successful_extractions, len(keyframe_files)
                    
                    # 执行关键帧匹配
                    successful_extractions, total_keyframe_files = match_keyframes_by_filename()
                    failed_extractions = max(0, total_keyframe_files - successful_extractions)
                    
                    if successful_extractions == 0:
                        # 检查目录中是否有其他文件
                        all_files = os.listdir(video_keyframes_dir) if os.path.exists(video_keyframes_dir) else []
                        logger.error(f"关键帧目录内容: {all_files}")
                        raise Exception("未提取到任何关键帧文件，请检查视频文件格式")

                    update_progress(20, f"关键帧提取完成，成功匹配 {successful_extractions} 个关键帧")
                    
                    if failed_extractions > 0:
                        st.warning(f"⚠️ 有 {failed_extractions} 个关键帧文件无法匹配到字幕片段")
                    else:
                        st.success(f"✅ 成功提取并匹配 {successful_extractions} 个关键帧")

                except Exception as e:
                    # 如果提取失败，清理关键帧路径
                    for data_item in subtitle_keyframe_data:
                        data_item['keyframe_paths'] = []
                    
                    # 清理创建的目录
                    try:
                        if os.path.exists(video_keyframes_dir):
                            import shutil
                            shutil.rmtree(video_keyframes_dir)
                    except Exception as cleanup_err:
                        logger.error(f"清理失败的关键帧目录时出错: {cleanup_err}")

                    raise Exception(f"关键帧提取失败: {str(e)}")

            """
            3. 关键帧与字幕数据验证和整理
            """
            update_progress(25, "正在验证关键帧与字幕数据...")
            
            # 统计关键帧提取情况
            segments_with_keyframes = [item for item in subtitle_keyframe_data if len(item['keyframe_paths']) > 0]
            segments_without_keyframes = [item for item in subtitle_keyframe_data if len(item['keyframe_paths']) == 0]
            
            
            logger.info(f"数据验证完成，共 {len(subtitle_keyframe_data)} 个字幕片段")
            
            # 对没有关键帧的片段发出警告
            if segments_without_keyframes:
                st.warning(f"⚠️ 有 {len(segments_without_keyframes)} 个字幕片段没有成功提取到关键帧，将仅使用字幕文本进行分析")
                for item in segments_without_keyframes:
                    logger.warning(f"字幕片段 {item['index']+1} 无关键帧: {item['subtitle_text'][:30]}...")
            
            st.info(f"📊 数据验证完成，共 {len(subtitle_keyframe_data)} 个字幕片段，其中 {len(segments_with_keyframes)} 个有关键帧")
            
            # 为有关键帧的数据添加调试信息
            for data_item in segments_with_keyframes:
                for j, keyframe_path in enumerate(data_item['keyframe_paths']):
                    filename = os.path.basename(keyframe_path)
                    logger.debug(f"字幕{data_item['index']+1}-帧{j+1}: {data_item['subtitle_text'][:20]}... -> {filename}")
            
            # 只有在重新提取关键帧时才保存匹配数据到关键帧目录
            if not using_cached_data:
                subtitle_keyframe_match_file = os.path.join(video_keyframes_dir, "subtitle_keyframe_match.json")
                with open(subtitle_keyframe_match_file, 'w', encoding='utf-8') as f:
                    # 创建一个可序列化的版本
                    serializable_data = []
                    # 获取当前采样参数
                    current_second_per_frame = config.frames.get('second_per_frame', None)
                    current_max_frames = 10
                    
                    for item in subtitle_keyframe_data:
                        serializable_item = {
                            "index": item["index"],
                            "subtitle_text": item["subtitle_text"],
                            "timestamp": item["timestamp"],  # 原始SRT时间戳格式
                            "duration": item["duration"],
                            "keyframe_paths": item["keyframe_paths"],
                            "has_keyframes": len(item["keyframe_paths"]) > 0,
                            # 添加采样参数信息用于缓存验证
                            "sampling_params": {
                                "second_per_frame": current_second_per_frame,
                                "max_frames": current_max_frames
                            }
                        }
                        serializable_data.append(serializable_item)
                    json.dump(serializable_data, f, ensure_ascii=False, indent=2)
                
                logger.info(f"字幕-关键帧匹配数据已保存到: {subtitle_keyframe_match_file}")

            # 保持所有数据，包括没有关键帧的片段
            
            """
            4. 画面理解与剧情梳理（逐个字幕片段分析）
            """
            vision_llm_provider = st.session_state.get('vision_llm_providers').lower()
            logger.info(f"使用 {vision_llm_provider.upper()} 进行视觉分析")

            try:
                # ===================初始化视觉分析器===================
                update_progress(35, "正在初始化视觉分析器...")

                # 从配置中获取相关配置
                vision_api_key = st.session_state.get(f'vision_{vision_llm_provider}_api_key')
                vision_model = st.session_state.get(f'vision_{vision_llm_provider}_model_name')
                vision_base_url = st.session_state.get(f'vision_{vision_llm_provider}_base_url')

                # 创建视觉分析器实例
                analyzer = create_vision_analyzer(
                    provider=vision_llm_provider,
                    api_key=vision_api_key,
                    model=vision_model,
                    base_url=vision_base_url
                )

                update_progress(40, "正在进行画面理解与剧情梳理...")

                # ===================创建异步事件循环===================
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # ===================并行分析字幕片段===================
                async def parallel_analyze_segments():
                    # 确保并发数量在合理范围内
                    concurrent_tasks = st.session_state.get('max_concurrent_LLM_requests')  
                    
                    logger.info(f"使用并发分析，最大并发数: {concurrent_tasks}")
                    st.info(f"🔄 配置并发分析: {concurrent_tasks} 个任务并行处理")

                    # 创建信号量控制并发数
                    semaphore = asyncio.Semaphore(concurrent_tasks)
                    
                    # 用于跟踪进度的共享变量
                    completed_count = {'value': 0}
                    total_tasks = len(subtitle_keyframe_data)
                    
                    async def analyze_single_segment(i, data_item):
                        """异步分析单个字幕片段"""
                        async with semaphore:  # 控制并发数
                            try:
                                # 获取字幕片段信息
                                subtitle_text = data_item['subtitle_text']
                                timestamp = data_item['timestamp'] 
                                keyframe_paths = data_item['keyframe_paths']
                                
                                # 构建分析prompt
                                if keyframe_paths:
                                    # 有关键帧：画面+字幕分析
                                    analysis_prompt = f"""
                                        我提供了 {len(keyframe_paths)} 张视频帧和对应的字幕内容，请进行画面理解与剧情梳理。
                                        图片是按时间顺序给出的。

                                        字幕时间段：{timestamp}
                                        持续时长：{duration} 秒
                                        说话人与字幕内容："{subtitle_text}"

                                        请仔细分析视频帧的内容，并结合字幕文本，完成以下任务：
                                        1. 画面理解：详细描述画面中的主要内容、人物、动作、场景。
                                        2. 剧情梳理：基于画面和字幕，理解这个片段在整个故事中的作用和意义

                                        请务必使用 JSON 格式输出你的结果：
                                        {{
                                            "scene_description": "详细的画面描述，包含主要内容、人物、动作和场景",
                                            "key_elements": ["列出重要的最多三个视觉元素"],
                                            "plot_analysis": "这个片段在剧情中的作用和意义",
                                            "content_summary": "对这个片段内容的简洁总结"
                                        }}
                                        请只返回 JSON 字符串，不要包含任何其他解释性文字。
                                    """                        
                                    # 进行视觉+文本分析
                                    try:
                                        segment_results = await analyzer.analyze_image_with_subtitle(
                                            images=keyframe_paths,
                                            prompt=analysis_prompt,
                                            index=i
                                        )

                                        # 存在响应
                                        if segment_results and len(segment_results) > 0:
                                            response_text = segment_results[0]['response']
                                            
                                            # 解析JSON响应
                                            try:
                                                analysis_data = parse_and_fix_json(response_text)
                                                
                                                if analysis_data:
                                                    # 保存分析结果到数据结构中
                                                    data_item['scene_description'] = analysis_data.get('scene_description', '')
                                                    data_item['key_elements'] = analysis_data.get('key_elements', [])
                                                    data_item['plot_analysis'] = analysis_data.get('plot_analysis', '')
                                                    data_item['content_summary'] = analysis_data.get('content_summary', '')
                                                    
                                                    # logger.info(f"字幕片段 {i+1} 画面理解完成")
                                                else:
                                                    # logger.error(f"字幕片段 {i+1} JSON解析失败")
                                                    # 使用原始响应作为描述
                                                    data_item['scene_description'] = response_text[:200] + "..."
                                                    data_item['content_summary'] = f"基于字幕：{subtitle_text}"
                                                
                                            except Exception as parse_error:
                                                logger.error(f"解析字幕片段 {i+1} 的分析结果失败: {parse_error}")
                                                # 使用原始响应作为描述
                                                data_item['scene_description'] = response_text[:200] + "..."
                                                data_item['content_summary'] = f"基于字幕：{subtitle_text}"
                                        else:
                                            logger.warning(f"字幕片段 {i+1} 分析失败，未返回结果")
                                            data_item['content_summary'] = f"基于字幕：{subtitle_text}"
                                            
                                    except Exception as segment_error:
                                        logger.error(f"字幕片段 {i+1} 分析出错")
                                        data_item['content_summary'] = f"基于字幕：{subtitle_text}"
                                else:
                                    # 没有关键帧：基于字幕内容进行文本分析（使用视觉分析器的文本处理能力）
                                    logger.info(f"字幕片段 {i+1} 没有关键帧，基于字幕进行文本内容分析")
                                    
                                    # 构建基于字幕的分析prompt
                                    text_analysis_prompt = f"""
                                        基于以下字幕内容，请进行深度文本分析和剧情理解。

                                        字幕时间段：{timestamp}
                                        字幕内容："{subtitle_text}"

                                        虽然没有画面信息，但请基于字幕文本内容，完成以下分析：
                                        1. 内容理解：从字幕推测可能的画面场景、人物动作、环境描述
                                        2. 情感分析：分析字幕传达和语气（如：积极、消极、中性、兴奋、平静、紧张等）
                                        3. 剧情推测：根据字幕内容推测这个片段在整体故事中的作用
                                        4. 关键信息提取：识别字幕中的重要信息点

                                        请务必使用 JSON 格式输出你的结果：
                                        {{
                                            "scene_description": "基于字幕推测的可能画面场景描述",
                                            "key_elements": ["从字幕中", "提取的", "关键信息点"],
                                            "plot_analysis": "这个片段在剧情中的推测作用和意义",
                                            "content_summary": "对这个字幕片段的深度理解总结"
                                        }}

                                        请只返回 JSON 字符串，不要包含任何其他解释性文字。
                                    """
                                    
                                    # 使用视觉分析器进行文本分析（不传入图片，只分析文本）
                                    text_segment_results = await analyzer.analyze_images(
                                        images=[],  # 空图片列表，只进行文本分析
                                        prompt=text_analysis_prompt,
                                        batch_size=1
                                    )
                                    
                                    if text_segment_results and len(text_segment_results) > 0:
                                        text_response = text_segment_results[0]['response']
                                        
                                        # 解析JSON响应
                                        try:
                                            text_analysis_data = parse_and_fix_json(text_response)
                                            if text_analysis_data:
                                                # 保存分析结果到数据结构中
                                                data_item['scene_description'] = text_analysis_data.get('scene_description', f"基于字幕推测：{subtitle_text}")
                                                data_item['key_elements'] = text_analysis_data.get('key_elements', [])
                                                data_item['plot_analysis'] = text_analysis_data.get('plot_analysis', f"基于字幕内容推测：{subtitle_text}")
                                                data_item['content_summary'] = text_analysis_data.get('content_summary', subtitle_text)
                                                
                                                logger.info(f"字幕片段 {i+1} 文本分析完成")
                                            else:
                                                logger.error(f"字幕片段 {i+1} 文本分析JSON解析失败")
                                                # 使用原始响应作为描述
                                                data_item['scene_description'] = f"文本分析结果：{text_response[:200]}..."
                                                data_item['content_summary'] = f"基于字幕：{subtitle_text}"
                                            
                                        except Exception as text_parse_error:
                                            logger.error(f"解析字幕片段 {i+1} 的文本分析结果失败: {text_parse_error}")
                                            # 使用原始响应作为描述
                                            data_item['scene_description'] = f"文本分析结果：{text_response[:200]}..."
                                            data_item['content_summary'] = f"基于字幕：{subtitle_text}"
                                    else:
                                        logger.warning(f"字幕片段 {i+1} 文本分析失败，未返回结果")
                                        data_item['scene_description'] = f"基于字幕推测：{subtitle_text}"
                                        data_item['content_summary'] = f"基于字幕：{subtitle_text}"
                                        
                            finally:
                                # 更新进度
                                completed_count['value'] += 1
                                current_progress = 40 + (completed_count['value'] / total_tasks) * 20  # 40%-60%的进度范围
                                update_progress(current_progress, f"已完成 {completed_count['value']}/{total_tasks} 个字幕片段分析...")

                    # 创建所有任务
                    tasks = [
                        analyze_single_segment(i, data_item) 
                        for i, data_item in enumerate(subtitle_keyframe_data)
                    ]
                    
                    # 执行所有任务并等待完成
                    await asyncio.gather(*tasks)

                # 运行并行分析
                loop.run_until_complete(parallel_analyze_segments())
                
                # 关闭事件循环
                loop.close()
                logger.info(f"完成 {len(subtitle_keyframe_data)} 个字幕片段的画面理解与剧情梳理")

                """
                5. 主题提取
                """
                update_progress(65, "正在进行主题提取...")
                
                # 从配置中获取文本生成相关配置  
                text_provider = config.app.get('text_llm_provider', 'gemini').lower()
                text_api_key = config.app.get(f'text_{text_provider}_api_key')
                text_model = config.app.get(f'text_{text_provider}_model_name')
                text_base_url = config.app.get(f'text_{text_provider}_base_url')
                themes_analyzer = create_text_analyzer(
                    provider=text_provider,
                    api_key=text_api_key,
                    model=text_model,
                    base_url=text_base_url
                )
                
                
                # 整合所有字幕和画面理解信息
                combined_content = []
                for i, data_item in enumerate(subtitle_keyframe_data):
                    content_block = {
                        "time": data_item['timestamp'],
                        "subtitle": data_item['subtitle_text'],
                        "scene_description": data_item.get('scene_description', ''),
                        "content_summary": data_item.get('content_summary', '')
                    }
                    combined_content.append(content_block)
                
                # 构建主题提取prompt
                # !markdown格式是否有必要
                content_summary = "\n".join([
                    f"时间段: {item['time']}\n字幕: {item['subtitle']}\n画面理解: {item['scene_description']}\n内容总结: {item['content_summary']}\n---"
                    for item in combined_content
                ])
                
                theme_extraction_prompt = f"""
                    基于以下视频内容的字幕和画面理解，请提取出这个视频的主要主题。

                    {content_summary}

                    请分析视频的核心主题，并按重要性排序。每个主题应该包含主题名称和详细描述。

                    请务必使用 JSON 格式输出：
                    {{
                    "themes": [
                        {{
                            "theme_name": "主题名称",
                            "theme_description": "主题的详细描述",
                            "relevance_score": 0.95
                        }},
                        {{
                            "theme_name": "次要主题名称", 
                            "theme_description": "次要主题的详细描述",
                            "relevance_score": 0.80
                        }}
                    ]
                    }}

                    请只返回 JSON 字符串，不要包含任何其他解释性文字。
                """
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                theme_response = loop.run_until_complete(
                    themes_analyzer.analyze_themes(
                        theme_extraction_prompt
                    )
                )
                loop.close()

                # 解析主题提取结果
                themes = []
                themes_data = parse_and_fix_json(theme_response)
                
                if themes_data:
                    themes = themes_data.get('themes', [])
                    
                    logger.info(f"成功提取 {len(themes)} 个主题")
                    for theme in themes:
                        logger.info(f"主题: {theme.get('theme_name', '')} (相关度: {theme.get('relevance_score', 0)})")
                else:
                    logger.error(f"主题提取结果解析失败")
                    # 创建默认主题
                    themes = [{
                        "theme_name": "默认主题",
                        "theme_description": "基于视频内容的综合主题",
                        "relevance_score": 1.0
                    }]
                
                """
                6. 生成解说文案
                """
                logger.info("开始生成解说文案")
                update_progress(80, "正在生成解说文案...")
                
                # 导入解说文案生成函数
                from app.services.generate_narration_script import generate_narration
                
                # 准备分析数据文件
                analysis_dir = os.path.join(utils.storage_dir(), "temp", "analysis")
                os.makedirs(analysis_dir, exist_ok=True)
                
                # 使用当前时间创建文件名
                now = datetime.now()
                timestamp_str = now.strftime("%Y%m%d_%H%M")
                
                # 创建专门针对粤语长视频的markdown转换函数
                def parse_health_video_to_markdown(subtitle_keyframe_data, themes):
                    """
                    将粤语长视频的字幕和画面分析数据转换为Markdown格式
                    针对粤语长视频的特点进行优化
                    """
                    markdown = "# 长视频内容分析\n\n"
                    
                    # 添加主题信息
                    # if themes:
                    #     markdown += "## 视频主题\n"
                    #     # 只显示第一个相关性最高的主题
                    #     theme = themes[0]
                    #     theme_name = theme.get('theme_name', '主题1')
                    #     theme_desc = theme.get('theme_description', '')
                    #     relevance = theme.get('relevance_score', 0)
                    #     markdown += f"- **{theme_name}** (相关度: {relevance:.2f}): {theme_desc}\n"
                    #     markdown += "\n"
                    
                    # 处理每个字幕片段
                    for i, data_item in enumerate(subtitle_keyframe_data, 1):
                        timestamp = data_item['timestamp']
                        subtitle_text = data_item['subtitle_text']
                        scene_description = data_item.get('scene_description', '')
                        key_elements = data_item.get('key_elements', [])
                        plot_analysis = data_item.get('plot_analysis', '')
                        content_summary = data_item.get('content_summary', '')
                        duration = data_item.get('duration', 0)

                        markdown += f"## 片段 {i}\n"
                        markdown += f"- **时间范围**: {timestamp}\n"
                        markdown += f"- **持续时间**: {duration:.2f}\n秒"
                        markdown += f"- **原始字幕(带说话人与BGM标识)**: {subtitle_text}\n"
                        
                        if scene_description:
                            markdown += f"- **画面描述**: {scene_description}\n"
                        
                        if key_elements:
                            elements_str = "、".join(key_elements)
                            markdown += f"- **关键要素**: {elements_str}\n"
                        
                        if plot_analysis:
                            markdown += f"- **内容分析**: {plot_analysis}\n"
                        
                        if content_summary:
                            markdown += f"- **片段总结**: {content_summary}\n"
                        
                        markdown += "\n"
                    
                    return markdown
                
                # 生成专门针对粤语长视频的markdown内容
                markdown_output = parse_health_video_to_markdown(subtitle_keyframe_data, themes)
                
                # 保存markdown内容以便调试
                markdown_file = os.path.join(analysis_dir, f"cantonese_long_video_markdown_{timestamp_str}.md")
                with open(markdown_file, 'w', encoding='utf-8') as f:
                    f.write(markdown_output)
                logger.info(f"Markdown内容已保存到: {markdown_file}")
                
                # 从配置中获取文本生成相关配置
                text_provider = config.app.get('text_llm_provider', 'gemini').lower()
                text_api_key = config.app.get(f'text_{text_provider}_api_key')
                text_model = config.app.get(f'text_{text_provider}_model_name')
                text_base_url = config.app.get(f'text_{text_provider}_base_url')
                
                llm_params = {
                    "text_provider": text_provider,
                    "text_api_key": text_api_key,
                    "text_model_name": text_model,
                    "text_base_url": text_base_url
                }
                check_video_config(llm_params)
                
                theme = themes[0]
                theme_name = theme.get('theme_name', '主题1')
                theme_desc = theme.get('theme_description', '')
                    
                # 生成解说文案 - 保持与原有函数的兼容性
                narration = generate_narration(
                    markdown_output,
                    text_api_key,
                    base_url=text_base_url,
                    model=text_model,
                    theme=theme_name,
                    theme_description=theme_desc
                )
                
                # 使用增强的JSON解析器
                narration_data = parse_and_fix_json(narration)
                
                if not narration_data or 'items' not in narration_data:
                    logger.error(f"解说文案JSON解析失败，原始内容: {narration[:200]}...")
                    raise Exception("解说文案格式错误，无法解析JSON或缺少items字段")
                
                narration_dict = narration_data['items']
  
                # 统计所有片段的总持续时间，复用现有的时间转换函数
                total_duration_ms = 0
                for item in narration_dict:
                    timestamp = item.get('timestamp', '')
                    if timestamp and '-' in timestamp:
                        try:
                            # 解析时间戳格式 '00:00:05,640-00:00:08,720'
                            start_str, end_str = timestamp.split('-')
                            # 将逗号替换为点号以适配to_ms函数的格式要求
                            start_str = start_str.replace(',', '.')
                            end_str = end_str.replace(',', '.')
                            # 使用现有的to_ms函数进行转换
                            start_ms = to_ms(start_str)
                            end_ms = to_ms(end_str)
                            duration_ms = end_ms - start_ms
                            total_duration_ms += duration_ms
                        except Exception as e:
                            logger.warning(f"解析时间戳失败: {timestamp}, 错误: {e}")
                            continue
                
                # 使用现有的to_hmsf函数转换为时分秒格式
                formatted_duration = to_hmsf(total_duration_ms)
                total_seconds = total_duration_ms / 1000.0
                
                logger.info(f"所有片段总持续时间: {formatted_duration} ({total_seconds:.2f}秒)")
                st.info(f"📊 视频总持续时间: {formatted_duration} (共{total_seconds:.2f}秒)")
                
                # 为 narration_dict 中每个 item 新增一个 OST: 2 的字段, 代表保留原声和配音
                narration_dict = [{**item, "OST": 2} for item in narration_dict]
                logger.info(f"解说文案生成完成，共 {len(narration_dict)} 个片段")
                
                # 结果转换为JSON字符串
                script = json.dumps(narration_dict, ensure_ascii=False, indent=2)

                """
                7. 保存结果
                """
                update_progress(90, "正在保存结果...")
                
                # 确保分析目录存在（已在上面创建）
                
                # 保存完整的数据结构
                primary_theme = themes[0] if themes else {
                    "theme_name": "粤语长视频主题",
                    "theme_description": "基于视频内容的综合主题",
                    "relevance_score": 1.0
                }
                
                full_data = {
                    "subtitle_segments": subtitle_keyframe_data,
                    "themes": themes,
                    "primary_theme": primary_theme,
                    "script_items": json.loads(script),
                    "total_duration": {
                        "seconds": total_seconds,
                        "formatted": formatted_duration,
                        "segments_count": len(narration_dict)
                    }
                }

                final_analysis_file = os.path.join(analysis_dir, f"cantonese_long_video_final_analysis_{timestamp_str}.json")
                with open(final_analysis_file, 'w', encoding='utf-8') as f:
                    json.dump(full_data, f, ensure_ascii=False, indent=2)
                
                # 保存脚本文件
                script_file = os.path.join(analysis_dir, f"cantonese_long_video_script_{timestamp_str}.json")
                with open(script_file, 'w', encoding='utf-8') as f:
                    f.write(script)
                
                logger.info(f"完整分析结果已保存到: {final_analysis_file}")
                logger.info(f"解说脚本已保存到: {script_file}")
                
                update_progress(100, "处理完成！")
                logger.info("粤语长视频脚本生成任务完成")

            except Exception as e:
                logger.exception(f"大模型处理过程中发生错误\n{traceback.format_exc()}")
                raise Exception(f"分析失败: {str(e)}")

            if script is None:
                st.error("生成脚本失败，请检查日志")
                st.stop()
                
            logger.info(f"粤语长视频解说脚本生成完成")
            
            if isinstance(script, list):
                st.session_state['video_clip_json'] = script
            elif isinstance(script, str):
                st.session_state['video_clip_json'] = json.loads(script)
                
            update_progress(100, "脚本生成完成")

        time.sleep(0.1)
        progress_bar.progress(100)
        status_text.text("🎉 脚本生成完成！")
        st.success("✅ 视频脚本生成成功！")

    except Exception as err:
        st.error(f"❌ 生成过程中发生错误: {str(err)}")
        logger.exception(f"生成脚本时发生错误\n{traceback.format_exc()}")
        return None
    finally:
        time.sleep(2)
        progress_bar.empty()
        status_text.empty()
        
def parse_and_fix_json(json_string):
    """
    解析并修复JSON字符串

    Args:
        json_string: 待解析的JSON字符串

    Returns:
        dict: 解析后的字典，如果解析失败返回None
    """
    if not json_string or not json_string.strip():
        logger.error("JSON字符串为空")
        return None
    
    try:
        result = repair_json(json_string, return_objects=True)
        if result == "":
            logger.error("调用repair_json库解析失败")
        else:
            return result
    except json.JSONDecodeError as e:
        logger.warning(f"调用repair_json库解析失败: {e}")
    
    # 清理字符串
    json_string = json_string.strip()
    
    # 尝试直接解析
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        logger.warning(f"直接JSON解析失败: {e}")
    
    # 尝试修复双大括号问题（LLM生成的常见问题）
    try:
        # 将双大括号替换为单大括号
        fixed_braces = json_string.replace('{{', '{').replace('}}', '}')
        logger.info("修复双大括号格式")
        return json.loads(fixed_braces)
    except json.JSONDecodeError as e:
        logger.debug(f"修复双大括号格式失败: {e}")
        # pass
    
   

    # 尝试提取JSON部分
    try:
        # 查找JSON代码块
        json_match = re.search(r'```json\s*(.*?)\s*```', json_string, re.DOTALL)
        if json_match:
            json_content = json_match.group(1).strip()
            logger.info("从代码块中提取JSON内容")
            return json.loads(json_content)
    except json.JSONDecodeError as e:
        logger.debug(f"从代码块提取JSON失败: {e}")

    # 尝试查找大括号包围的内容
    try:
        # 查找第一个 { 到最后一个 } 的内容
        start_idx = json_string.find('{')
        end_idx = json_string.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_content = json_string[start_idx:end_idx+1]
            logger.info("提取大括号包围的JSON内容")
            return json.loads(json_content)
    except json.JSONDecodeError:
        pass

    # 尝试综合修复JSON格式问题
    try:
        fixed_json = json_string

        # 1. 修复双大括号问题
        fixed_json = fixed_json.replace('{{', '{').replace('}}', '}')

        # 2. 提取JSON内容（如果有其他文本包围）
        start_idx = fixed_json.find('{')
        end_idx = fixed_json.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            fixed_json = fixed_json[start_idx:end_idx+1]

        # 3. 移除注释
        fixed_json = re.sub(r'#.*', '', fixed_json)
        fixed_json = re.sub(r'//.*', '', fixed_json)

        # 4. 移除多余的逗号
        fixed_json = re.sub(r',\s*}', '}', fixed_json)
        fixed_json = re.sub(r',\s*]', ']', fixed_json)

        # 5. 修复单引号
        fixed_json = re.sub(r"'([^']*)':", r'"\1":', fixed_json)
        
        # 5.1 把所有的单引号改成双引号
        fixed_json = fixed_json.replace("'", '"')
        
        # 5.2 把中文双引号改成转义英文双引号
        fixed_json = fixed_json.replace('“', '\\"').replace('”', '\\"')
        
        # 6. 修复没有引号的属性名
        fixed_json = re.sub(r'(\w+)(\s*):', r'"\1"\2:', fixed_json)

        # 7. 修复重复的引号
        fixed_json = re.sub(r'""([^"]*?)""', r'"\1"', fixed_json)

        logger.info("尝试综合修复JSON格式问题后解析")
        return json.loads(fixed_json)
    except json.JSONDecodeError as e:
        logger.debug(f"综合修复失败: {e}")
        pass

    # 如果所有方法都失败，返回None
    logger.error(f"所有JSON解析方法都失败，原始内容: {json_string}...")
    return None