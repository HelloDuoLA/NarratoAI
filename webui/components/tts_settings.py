import streamlit as st
import os
import subprocess
import tempfile
from loguru import logger
import alibabacloud_oss_v2 as oss
import os
from typing import Optional
import urllib.parse
import json
from urllib import request
from http import HTTPStatus
from datetime import datetime
import dashscope
import shutil
from .merge_speaker_srt import convert_json_to_srt_for_llm 


# 定义临时目录路径
TEMP_TTS_DIR = os.path.join("storage", "temp", "TTS")

# 确保临时目录存在
os.makedirs(TEMP_TTS_DIR, exist_ok=True)

def clean_temp_dir():
    """清空临时目录"""
    if os.path.exists(TEMP_TTS_DIR):
        for file in os.listdir(TEMP_TTS_DIR):
            file_path = os.path.join(TEMP_TTS_DIR, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                logger.error(f"清理临时文件失败: {str(e)}")


def copy_files_to_resource(video_path: str, result: dict, original_filename: str):
    """
    将视频文件和SRT字幕文件复制到资源目录
    
    Args:
        video_path: 原始视频文件路径
        result: 处理结果字典
        original_filename: 原始文件名
    """
    try:
        # 定义目标目录
        srt_target_dir = "/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/NarratoAI/resource/srt"
        videos_target_dir = "/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/NarratoAI/resource/videos"
        
        # 确保目标目录存在
        os.makedirs(srt_target_dir, exist_ok=True)
        os.makedirs(videos_target_dir, exist_ok=True)
        
        copy_success = []
        copy_errors = []
        
        # 复制视频文件
        if os.path.exists(video_path):
            video_target_path = os.path.join(videos_target_dir, original_filename)
            try:
                shutil.copy2(video_path, video_target_path)
                copy_success.append(f"📹 视频文件: {original_filename}")
                logger.info(f"视频文件复制成功: {video_target_path}")
            except Exception as e:
                copy_errors.append(f"视频文件复制失败: {str(e)}")
                logger.error(f"视频文件复制失败: {str(e)}")
        
        # 复制SRT字幕文件
        srt_file_path = result.get("long_subtitle_file")
        if srt_file_path and os.path.exists(srt_file_path):
            srt_filename = os.path.basename(srt_file_path)
            srt_target_path = os.path.join(srt_target_dir, srt_filename)
            try:
                shutil.copy2(srt_file_path, srt_target_path)
                copy_success.append(f"📄 字幕文件: {srt_filename}")
                logger.info(f"SRT文件复制成功: {srt_target_path}")
            except Exception as e:
                copy_errors.append(f"字幕文件复制失败: {str(e)}")
                logger.error(f"SRT文件复制失败: {str(e)}")
        
        # 显示复制结果
        if copy_success:
            st.success("✅ 视频、字幕文件复制完成！可以在后续的环节中选取使用！")
            # for success_msg in copy_success:
            #     st.text(success_msg)
            
            # 显示目标路径
            # st.info("📂 文件已复制到以下目录：")
            # st.text(f"🎬 视频目录: {videos_target_dir}")
            # st.text(f"📝 字幕目录: {srt_target_dir}")
            
            # 添加清理按钮选项
            # if st.button("🧹 清理处理记录", key="clear_session"):
            #     # 清理session state
            #     if 'tts_result' in st.session_state:
            #         del st.session_state['tts_result']
            #     if 'original_video_path' in st.session_state:
            #         del st.session_state['original_video_path']
            #     if 'original_filename' in st.session_state:
            #         del st.session_state['original_filename']
            #     st.rerun()
        
        if copy_errors:
            st.error("❌ 部分文件复制失败：")
            for error_msg in copy_errors:
                st.text(error_msg)
                
    except Exception as e:
        st.error(f"❌ 文件复制过程中出现错误: {str(e)}")
        logger.error(f"文件复制过程出错: {str(e)}")
def render_tts_settings(tr):
    """渲染语音识别设置部分"""
    # clean_temp_dir()
    with st.expander(tr("语音识别"), expanded=True):
        # 上传视频文件
        uploaded_file = st.file_uploader(
            tr("上传视频进行语音识别"),
            type=["mp4", "avi", "mov", "wmv", "flv", "webm"],
            accept_multiple_files=False,
            key="video_upload"
        )
        
        if uploaded_file is not None:
            # 显示文件信息
            file_size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
            
            # 直接保存文件到指定目录
            save_directory = os.path.join("storage", "uploads")
            os.makedirs(save_directory, exist_ok=True)
            
            file_path = os.path.join(save_directory, uploaded_file.name)
            
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getvalue())
            
            # 创建一个占位符来控制上传成功信息的显示
            upload_status_placeholder = st.empty()
            
            # 如果还没有处理结果，显示上传成功信息
            if 'tts_result' not in st.session_state or not st.session_state['tts_result']:
                with upload_status_placeholder.container():
                    st.success(f"✅ {tr('视频上传成功')}")
            
            # 添加警告信息
            if file_size_mb > 100:
                st.warning("⚠️ 视频文件较大，处理时间可能较长，请耐心等待...")
            
            if st.button(tr("进行语音识别"), key="start_speech_recognition"):
                # 清除上传状态信息
                upload_status_placeholder.empty()
                
                # 创建一个占位符来显示动态状态
                status_placeholder = st.empty()
                progress_placeholder = st.empty()
                
                with status_placeholder.container():
                    st.info("🚀 正在启动语音识别流程...")
                    st.info("📊 处理流程：音频提取 → 音源分离 → 云端上传 → 语音识别 → 字幕生成")
                
                # 获取视频文件名（不含扩展名）作为前缀
                video_name = os.path.splitext(uploaded_file.name)[0]
                
                # 执行语音识别流程
                result = perform_speech_recognition(file_path, video_name, tr, status_placeholder, progress_placeholder)
                
                if result:
                    # 将结果保存到session state中，以便后续使用
                    st.session_state['tts_result'] = result
                    st.session_state['original_video_path'] = file_path
                    st.session_state['original_filename'] = uploaded_file.name
                    
                    # 清除状态占位符，显示最终结果
                    status_placeholder.empty()
                    progress_placeholder.empty()
                    
                    st.success("🎉 语音识别完成！")
                    
                    # 显示字幕内容
                    if os.path.exists(result.get("long_subtitle_file", "")):
                        with open(result["long_subtitle_file"], 'r', encoding='utf-8') as f:
                            srt_content = f.read()
                        
                        # 直接显示字幕内容，使用折叠式文本区域
                        st.subheader("📋 完整字幕内容")
                        st.text_area(
                            "字幕内容",
                            srt_content,
                            height=300,
                            help="完整的SRT字幕文件内容，可以复制使用"
                        )
                        
                else:
                    # 清除状态占位符，显示错误信息
                    status_placeholder.empty()
                    progress_placeholder.empty()
                    st.error("❌ 语音识别失败，请检查视频文件或网络连接")
        
        # 在expander外部检查并显示复制按钮
        if 'tts_result' in st.session_state and st.session_state['tts_result']:
            st.divider()
            if st.button("📁 复制文件到资源目录", key="copy_files_to_resource", type="primary"):
                copy_files_to_resource(
                    st.session_state['original_video_path'], 
                    st.session_state['tts_result'], 
                    st.session_state['original_filename']
                )


def perform_speech_recognition(video_path: str, video_name: str, tr, status_placeholder, progress_placeholder) -> Optional[dict]:
    """
    执行完整的语音识别流程
    
    Args:
        video_path: 视频文件路径
        video_name: 视频文件名（不含扩展名），用作文件前缀
        tr: 翻译函数
        status_placeholder: 状态显示占位符
        progress_placeholder: 进度显示占位符
    
    Returns:
        处理结果字典，包含所有生成的文件路径
    """
    try:
        # 创建临时工作目录
        work_dir = os.path.join(TEMP_TTS_DIR, f"{video_name}_processing")
        os.makedirs(work_dir, exist_ok=True)
        
        # 预定义文件路径
        audio_path = os.path.join(work_dir, f"audio.wav")
        vocals_path = os.path.join(work_dir, f"{video_name}_vocals.wav")
        accompaniment_path = os.path.join(work_dir, f"{video_name}_accompaniment.wav")
        aliyun_subtitle_path = os.path.join(work_dir, f"{video_name}_aliyun_subtitle.json")
        llm_srt_path = os.path.join(work_dir, f"{video_name}.srt")
        
        # 检查是否已有SRT字幕文件
        if os.path.exists(llm_srt_path) and os.path.getsize(llm_srt_path) > 0:
            with status_placeholder.container():
                st.success("✅ 发现已存在的SRT字幕文件，跳过所有处理步骤")
                st.info(f"📄 使用现有文件: {os.path.basename(llm_srt_path)}")
        else:
            # 检查是否已有阿里云字幕JSON文件
            if os.path.exists(aliyun_subtitle_path) and os.path.getsize(aliyun_subtitle_path) > 0:
                with status_placeholder.container():
                    st.success("✅ 发现已存在的语音识别结果，直接转换为SRT格式")
                    st.info("📝 步骤 5/5: 正在生成SRT字幕文件...")
                
                convert_json_to_srt_for_llm(aliyun_subtitle_path, llm_srt_path)
            else:
                # 需要进行语音识别，先检查音频文件
                current_vocals_path = vocals_path
                
                # 步骤1: 检查音频提取
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                    with status_placeholder.container():
                        st.success("✅ 发现已存在的音频文件，跳过音频提取")
                        st.info(f"🎵 使用现有音频: {os.path.basename(audio_path)}")
                else:
                    # 更新状态：步骤1 - 音频提取
                    with status_placeholder.container():
                        st.info("🎵 步骤 1/5: 正在从视频中提取音频...")
                    
                    audio_path = extract_audio_from_video(video_path, video_name, work_dir, status_placeholder)
                    if not audio_path:
                        with status_placeholder.container():
                            st.error("❌ 音频提取失败")
                        return None
                
                # 步骤2: 检查人声分离
                if os.path.exists(vocals_path) and os.path.getsize(vocals_path) > 0:
                    with status_placeholder.container():
                        st.success("✅ 发现已存在的人声文件，跳过音源分离")
                        st.info(f"🎤 使用现有人声: {os.path.basename(vocals_path)}")
                    current_vocals_path = vocals_path
                    final_accompaniment_path = accompaniment_path if os.path.exists(accompaniment_path) else None
                else:
                    # 更新状态：步骤2 - 音源分离
                    with status_placeholder.container():
                        st.success("✅ 音频提取成功")
                        st.info("🎤 步骤 2/5: 正在分离人声和背景音乐...")
                    
                    current_vocals_path, final_accompaniment_path = separate_audio_sources(audio_path, video_name, work_dir, status_placeholder)
                    if not current_vocals_path:
                        with status_placeholder.container():
                            st.error("❌ 音源分离失败")
                        return None
                
                # 步骤3: 上传音频到OSS
                with status_placeholder.container():
                    st.success("✅ 音源分离完成")
                    st.info("☁️ 步骤 3/5: 正在上传音频到云存储...")
                
                oss_audio_url = upload_audio_to_oss(current_vocals_path, f"{video_name}_vocals.wav", status_placeholder)
                if not oss_audio_url:
                    with status_placeholder.container():
                        st.error("❌ 音频上传失败")
                    return None
                
                # 步骤4: 语音识别
                with status_placeholder.container():
                    st.success("✅ 音频上传成功")
                    st.info("🤖 步骤 4/5: 正在进行语音识别...")
                
                aliyun_subtitle = use_online_asr_service(oss_audio_url, aliyun_subtitle_path, status_placeholder)
                if not aliyun_subtitle:
                    with status_placeholder.container():
                        st.error("❌ 语音识别失败")
                    return None
                
                # 步骤5: 生成字幕文件
                with status_placeholder.container():
                    st.success("✅ 语音识别完成")
                    st.info("📝 步骤 5/5: 正在生成SRT字幕文件...")
                
                convert_json_to_srt_for_llm(aliyun_subtitle_path, llm_srt_path)
        
        # 检查SRT文件是否生成成功
        if os.path.exists(llm_srt_path):
            file_size = os.path.getsize(llm_srt_path)
            if file_size > 0:
                with status_placeholder.container():
                    st.success("✅ 所有步骤完成！")
                    st.success(f"📄 SRT字幕文件生成成功 - 大小: {file_size} 字节")
            else:
                with status_placeholder.container():
                    st.warning("⚠️ SRT字幕文件为空")
        else:
            with status_placeholder.container():
                st.error("❌ SRT字幕文件生成失败")
        
        # 整理返回结果，使用实际的文件路径
        result = {
            "video_name": video_name,
            "original_audio": audio_path if os.path.exists(audio_path) else None,
            "vocals_audio": current_vocals_path if 'current_vocals_path' in locals() else vocals_path,
            "accompaniment_audio": final_accompaniment_path if 'final_accompaniment_path' in locals() and final_accompaniment_path and os.path.exists(final_accompaniment_path) else None,
            "aliyun_subtitle_file": aliyun_subtitle_path,
            "long_subtitle_file": llm_srt_path,
            "oss_audio_url": oss_audio_url if 'oss_audio_url' in locals() else None,
            "work_directory": work_dir
        }
        
        return result
        
    except Exception as e:
        with status_placeholder.container():
            st.error(f"❌ 语音识别流程出现错误: {str(e)}")
            st.error("🔧 请检查以下可能的问题:")
            st.text("• 网络连接是否正常")
            st.text("• 阿里云API密钥是否正确配置")
            st.text("• 视频文件是否包含清晰的音频")
            st.text("• FFmpeg是否正确安装")
        
        logger.error(f"语音识别流程失败: {str(e)}")
        return None
def extract_audio_from_video(video_path: str, video_name: str, work_dir: str, status_placeholder) -> Optional[str]:
    """使用FFMPEG从视频中提取音频"""
    audio_path = os.path.join(work_dir, f"audio.wav")
    
    # 使用FFmpeg提取音频
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn",  # 不包含视频
        "-acodec", "pcm_s16le",  # 16位PCM编码
        "-ar", "48000",  # 采样率48kHz
        "-ac", "1",  # 单声道
        "-y",  # 覆盖输出文件
        audio_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg音频提取失败: {result.stderr}")
        return None
        
    # 检查生成的音频文件
    if not os.path.exists(audio_path):
        logger.error(f"音频文件未生成: {audio_path}")
        return None
        
    # 记录成功信息到日志
    file_size = os.path.getsize(audio_path) / (1024 * 1024)  # MB
    logger.info(f"音频提取成功: {audio_path}, 大小: {file_size:.2f} MB")
    return audio_path


def check_spleeter_availability() -> tuple[bool, list[str]]:
    """
    检查spleeter的可用性，返回是否可用和命令前缀
    
    Returns:
        tuple: (是否可用, 命令前缀列表)
    """
    # 方法1：检查是否有spleeter conda环境
    try:
        result = subprocess.run(["conda", "env", "list"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            # 检查环境列表中是否包含spleeter
            env_lines = result.stdout.strip().split('\n')
            for line in env_lines:
                if 'spleeter' in line.lower() and not line.startswith('#'):
                    logger.info("发现spleeter conda环境")
                    return True, ["conda", "run", "-n", "spleeter"]
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.debug(f"检查conda环境失败: {e}")
    
    # 方法2：直接检查spleeter命令是否可用
    try:
        result = subprocess.run(["spleeter", "--help"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            logger.info("发现系统级spleeter命令")
            return True, []
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.debug(f"检查系统spleeter失败: {e}")
    
    logger.warning("未找到可用的spleeter")
    return False, []


def separate_audio_sources(audio_path: str, video_name: str, work_dir: str, status_placeholder) -> tuple[Optional[str], Optional[str]]:
    """使用Spleeter分离人声和背景音乐"""
    # 检查spleeter可用性
    spleeter_available, spleeter_cmd_prefix = check_spleeter_availability()
    
    if not spleeter_available:
        logger.warning("Spleeter不可用，跳过音源分离步骤")
        return audio_path, None
    
    # Spleeter输出目录
    output_dir = os.path.join(work_dir, "separated")
    os.makedirs(output_dir, exist_ok=True)
    
    # 使用Spleeter进行音源分离
    cmd = spleeter_cmd_prefix + [
        "spleeter", "separate",
        "-p", "spleeter:2stems",  # 使用2stems模型分离人声和背景
        "-d", "5000",
        "-o", output_dir,
        audio_path
    ]
    
    logger.info(f"执行Spleeter命令: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # 10分钟超时
    
    if result.returncode != 0:
        logger.error(f"Spleeter分离失败: {result.stderr}")
        # 如果Spleeter失败，直接使用原音频作为人声
        return audio_path, None
    
    logger.info("Spleeter音源分离执行成功")
    
    # Spleeter输出文件路径
    audio_name = os.path.splitext(os.path.basename(audio_path))[0]
    vocals_path = os.path.join(output_dir, audio_name, "vocals.wav")
    accompaniment_path = os.path.join(output_dir, audio_name, "accompaniment.wav")
    
    # 重命名文件以包含视频名前缀
    final_vocals_path = os.path.join(work_dir, f"{video_name}_vocals.wav")
    final_accompaniment_path = os.path.join(work_dir, f"{video_name}_accompaniment.wav")
    
    if os.path.exists(vocals_path):
        os.rename(vocals_path, final_vocals_path)
        vocal_size = os.path.getsize(final_vocals_path) / (1024 * 1024)
        logger.info(f"人声分离成功: {final_vocals_path}, 大小: {vocal_size:.2f} MB")
    else:
        logger.warning("人声文件未生成，使用原音频")
        final_vocals_path = audio_path
        
    if os.path.exists(accompaniment_path):
        os.rename(accompaniment_path, final_accompaniment_path)
        bg_size = os.path.getsize(final_accompaniment_path) / (1024 * 1024)
        logger.info(f"背景音乐分离成功: {final_accompaniment_path}, 大小: {bg_size:.2f} MB")
    else:
        final_accompaniment_path = None
        logger.info("未检测到明显背景音乐")
    
    return final_vocals_path, final_accompaniment_path


def upload_audio_to_oss(local_audio_path: str, object_key: Optional[str] = None, status_placeholder=None) -> Optional[str]:
    """
    上传音频文件到阿里云OSS并返回下载链接
    
    Args:
        local_audio_path: 本地音频文件路径
        object_key: OSS对象键（文件在OSS中的路径和名称），如果未提供则使用文件名
    
    Returns:
        音频文件的下载链接，如果上传失败则返回None
    """
    # 检查本地文件是否存在
    if not os.path.exists(local_audio_path):
        logger.error(f"本地音频文件不存在: {local_audio_path}")
        return None
    
    # 如果没有提供object_key，则使用文件名，并将空格替换为下划线
    if object_key is None:
        object_key = os.path.basename(local_audio_path)
    
    # 将object_key中的空格替换为下划线，避免URL问题
    object_key = object_key.replace(' ', '_')
    
    # 记录上传信息
    file_size = os.path.getsize(local_audio_path) / (1024 * 1024)
    logger.info(f"准备上传音频文件 ({file_size:.2f} MB) 到云存储...")
    
    # 从环境变量中加载凭证信息，用于身份验证
    credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()

    # 加载SDK的默认配置，并设置凭证提供者
    cfg = oss.config.load_default()
    cfg.credentials_provider = credentials_provider

    # 设置Region
    cfg.region = 'cn-shenzhen'

    # 使用配置好的信息创建OSS客户端
    client = oss.Client(cfg)
    
    # 检查文件是否已存在
    try:
        # 尝试获取对象元数据来检查文件是否存在
        client.head_object(oss.HeadObjectRequest(
            bucket="baidulic-shenzhen",
            key=object_key
        ))
        # 如果没有抛出异常，说明文件已存在
        logger.info(f"文件已存在于OSS中: {object_key}")
        # 生成并返回现有文件URL
        file_url = f"https://baidulic-shenzhen.oss-cn-shenzhen.aliyuncs.com/{urllib.parse.quote(object_key)}"
        return file_url
    except Exception:
        # 文件不存在，继续上传流程
        pass

    # 读取本地音频文件并上传
    with open(local_audio_path, 'rb') as file_obj:
        result = client.put_object(oss.PutObjectRequest(
            bucket="baidulic-shenzhen",
            key=object_key,
            body=file_obj,
        ))
    
    # 检查上传结果
    if result.status_code == 200:
        logger.info(f"音频上传成功: {object_key}")
        # 生成文件URL，对特殊字符进行URL编码
        file_url = f"https://baidulic-shenzhen.oss-cn-shenzhen.aliyuncs.com/{urllib.parse.quote(object_key)}"
        return file_url
    else:
        logger.error(f"音频上传失败，状态码: {result.status_code}")
        return None


def use_online_asr_service(oss_audio_url: str, subtitle_path: str, status_placeholder=None):
    """
    使用DashScope在线语音识别服务
    
    Args:
        oss_audio_url: OSS音频文件URL
        subtitle_path: 字幕文件保存路径
    
    Returns:
        返回阿里云格式的字幕内容
    """
    # 配置API Key
    dashscope.api_key = 'sk-e84a65ec9a6e44fda41e548930900ff0'
    logger.info(f"使用OSS音频URL进行语音识别: {oss_audio_url}")
    
    # 提交异步识别任务
    task_response = dashscope.audio.asr.Transcription.async_call(
        model='paraformer-v2',
        file_urls=[oss_audio_url],
        language_hints=['yue', "zh"],  # 支持粤语和中文
        timestamp_alignment_enabled=True,  # 启用时间戳对齐
        diarization_enabled=True  # 启用说话人分离
    )
    
    if task_response.status_code != HTTPStatus.OK:
        logger.error(f"任务提交失败: {task_response.output}")
        return None
    
    task_id = task_response.output.task_id
    logger.info(f"任务ID: {task_id}")
    
    # 等待任务完成
    transcription_response = dashscope.audio.asr.Transcription.wait(task=task_id)
    
    if transcription_response.status_code == HTTPStatus.OK:
        results = transcription_response.output['results']
        logger.info(f"识别完成，共 {len(results)} 个结果")
        
        for idx, transcription in enumerate(results, 1):
            url = transcription['transcription_url']
            logger.info(f"下载第 {idx} 个识别结果...")
            
            # 下载识别结果
            result = json.loads(request.urlopen(url).read().decode('utf8'))
            
            # 保存结果到文件
            with open(subtitle_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=4, ensure_ascii=False)
            
            logger.info(f'Result {idx} saved to: {subtitle_path}')
            
            # 显示识别结果统计
            if 'sentences' in result:
                sentence_count = len(result['sentences'])
                logger.info(f"识别到 {sentence_count} 个句子")
            
        logger.info('语音识别完成!')
        return result
    else:
        error_msg = transcription_response.output.message
        logger.error(f'语音识别错误: {error_msg}')
        return None