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
from .aliyun_to_srt import convert_json_to_srt 


# 定义临时目录路径
TEMP_TTS_DIR = os.path.join("storage", "temp", "TTS")

# 确保临时目录存在
os.makedirs(TEMP_TTS_DIR, exist_ok=True)


def perform_speech_recognition(video_path: str, video_name: str) -> Optional[dict]:
    """
    执行完整的语音识别流程
    
    Args:
        video_path: 视频文件路径
        video_name: 视频文件名（不含扩展名），用作文件前缀
    
    Returns:
        处理结果字典，包含所有生成的文件路径
    """
    try:
        # 创建临时工作目录
        work_dir = os.path.join(TEMP_TTS_DIR, f"{video_name}_processing")
        os.makedirs(work_dir, exist_ok=True)
        
        # 预定义文件路径
        audio_path = os.path.join(work_dir, f"audio.wav")
        vocals_path = os.path.join(work_dir, f"vocals.wav")
        accompaniment_path = os.path.join(work_dir, f"accompaniment.wav")
        aliyun_subtitle_path = os.path.join(work_dir, f"aliyun_subtitle.json")
        final_srt_path = os.path.join(work_dir, f"{video_name}.srt")
        
        # 检查是否已有SRT字幕文件
        if os.path.exists(final_srt_path) and os.path.getsize(final_srt_path) > 0:
            logger.info("✅ 发现已存在的SRT字幕文件，跳过所有处理步骤")
            logger.info(f"📄 使用现有文件: {os.path.basename(final_srt_path)}")
        else:
            # 检查是否已有阿里云字幕JSON文件
            if os.path.exists(aliyun_subtitle_path) and os.path.getsize(aliyun_subtitle_path) > 0:
                logger.info("✅ 发现已存在的语音识别结果，直接转换为SRT格式")
                logger.info("📝 步骤 5/5: 正在生成SRT字幕文件...")
                
                convert_json_to_srt(aliyun_subtitle_path, final_srt_path)
            else:
                # 需要进行语音识别，先检查音频文件
                current_vocals_path = vocals_path
                
                # 步骤1: 检查音频提取
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                    logger.info("✅ 发现已存在的音频文件，跳过音频提取")
                    logger.info(f"🎵 使用现有音频: {os.path.basename(audio_path)}")
                else:
                    # 更新状态：步骤1 - 音频提取
                    logger.info("🎵 步骤 1/5: 正在从视频中提取音频...")
                    
                    audio_path = extract_audio_from_video(video_path, video_name, work_dir)
                    if not audio_path:
                        logger.error("❌ 音频提取失败")
                        return None
                
                # 步骤2: 检查人声分离
                if os.path.exists(vocals_path) and os.path.getsize(vocals_path) > 0:
                    logger.info("✅ 发现已存在的人声文件，跳过音源分离")
                    logger.info(f"🎤 使用现有人声: {os.path.basename(vocals_path)}")
                    current_vocals_path = vocals_path
                    final_accompaniment_path = accompaniment_path if os.path.exists(accompaniment_path) else None
                else:
                    # 更新状态：步骤2 - 音源分离
                    logger.info("✅ 音频提取成功")
                    logger.info("🎤 步骤 2/5: 正在分离人声和背景音乐...")
                    
                    current_vocals_path, final_accompaniment_path = separate_audio_sources(audio_path, video_name, work_dir)
                    if not current_vocals_path:
                        logger.error("❌ 音源分离失败")
                        return None
                
                # 步骤3: 上传音频到OSS
                logger.info("✅ 音源分离完成")
                logger.info("☁️ 步骤 3/5: 正在上传音频到云存储...")
                
                oss_audio_url = upload_audio_to_oss(current_vocals_path, f"{video_name}_vocals.wav")
                if not oss_audio_url:
                    logger.error("❌ 音频上传失败")
                    return None
                
                # 步骤4: 语音识别
                logger.info("✅ 音频上传成功")
                logger.info("🤖 步骤 4/5: 正在进行语音识别...")
                
                aliyun_subtitle = use_online_asr_service(oss_audio_url, aliyun_subtitle_path)
                if not aliyun_subtitle:
                    logger.error("❌ 语音识别失败")
                    return None
                
                # 步骤5: 生成字幕文件
                logger.info("✅ 语音识别完成")
                logger.info("📝 步骤 5/5: 正在生成SRT字幕文件...")
                
                convert_json_to_srt(aliyun_subtitle_path, final_srt_path)
        
        # 检查SRT文件是否生成成功
        if os.path.exists(final_srt_path):
            file_size = os.path.getsize(final_srt_path)
            if file_size > 0:
                logger.info("✅ 所有步骤完成！")
                logger.info(f"📄 SRT字幕文件生成成功 - 大小: {file_size} 字节")
            else:
                logger.warning("⚠️ SRT字幕文件为空")
        else:
            logger.error("❌ SRT字幕文件生成失败")
        
        # 整理返回结果，使用实际的文件路径
        result = {
            "video_name": video_name,
            "original_audio": audio_path if os.path.exists(audio_path) else None,
            "vocals_audio": current_vocals_path if 'current_vocals_path' in locals() else vocals_path,
            "accompaniment_audio": final_accompaniment_path if 'final_accompaniment_path' in locals() and final_accompaniment_path and os.path.exists(final_accompaniment_path) else None,
            "aliyun_subtitle_file": aliyun_subtitle_path,
            "final_subtitle_file": final_srt_path,
            "oss_audio_url": oss_audio_url if 'oss_audio_url' in locals() else None,
            "work_directory": work_dir
        }
        
        return result
        
    except Exception as e:
        logger.error(f"❌ 语音识别流程出现错误: {str(e)}")
        logger.error("🔧 请检查以下可能的问题:")
        logger.error("• 网络连接是否正常")
        logger.error("• 阿里云API密钥是否正确配置")
        logger.error("• 视频文件是否包含清晰的音频")
        logger.error("• FFmpeg是否正确安装")
        
        logger.error(f"语音识别流程失败: {str(e)}")
        return None
def extract_audio_from_video(video_path: str, video_name: str, work_dir: str) -> Optional[str]:
    """使用FFMPEG从视频中提取音频"""
    audio_path = os.path.join(work_dir, f"audio.wav")
    
    # 首先检查视频文件的音频流信息
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", video_path
    ]
    
    try:
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        if probe_result.returncode == 0:
            import json
            probe_data = json.loads(probe_result.stdout)
            audio_streams = [s for s in probe_data.get('streams', []) if s.get('codec_type') == 'audio']
            
            if not audio_streams:
                logger.error(f"视频文件 {video_path} 不包含音频流")
                return None
            else:
                logger.info(f"检测到 {len(audio_streams)} 个音频流")
                for i, stream in enumerate(audio_streams):
                    codec = stream.get('codec_name', 'unknown')
                    sample_rate = stream.get('sample_rate', 'unknown')
                    channels = stream.get('channels', 'unknown')
                    logger.info(f"音频流 {i}: 编码={codec}, 采样率={sample_rate}, 声道={channels}")
        else:
            logger.warning("无法探测视频文件信息，继续尝试提取音频")
    except Exception as e:
        logger.warning(f"探测视频信息时出错: {e}，继续尝试提取音频")
    
    # 使用FFmpeg提取音频，添加更宽松的参数
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn",  # 不包含视频
        "-acodec", "pcm_s16le",  # 16位PCM编码
        "-ar", "48000",  # 采样率48kHz
        "-ac", "1",  # 单声道
        "-f", "wav",  # 明确指定输出格式
        "-y",  # 覆盖输出文件
        audio_path
    ]
    
    # 如果标准参数失败，尝试自动音频参数
    logger.info(f"执行FFmpeg命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        logger.warning(f"标准参数提取失败，尝试自动参数: {result.stderr}")
        
        # 尝试使用自动参数
        cmd_auto = [
            "ffmpeg", "-i", video_path,
            "-vn",  # 不包含视频
            "-acodec", "pcm_s16le",  # 16位PCM编码
            "-f", "wav",  # 明确指定输出格式
            "-y",  # 覆盖输出文件
            audio_path
        ]
        
        logger.info(f"重试FFmpeg命令（自动参数）: {' '.join(cmd_auto)}")
        result = subprocess.run(cmd_auto, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg音频提取失败: {result.stderr}")
            logger.error("建议检查:")
            logger.error("• 视频文件是否损坏")
            logger.error("• 视频文件是否包含音频轨道")
            logger.error("• FFmpeg版本是否支持该视频格式")
            return None
        
    # 检查生成的音频文件
    if not os.path.exists(audio_path):
        logger.error(f"音频文件未生成: {audio_path}")
        return None
        
    # 检查音频文件是否为空
    file_size = os.path.getsize(audio_path)
    if file_size == 0:
        logger.error("生成的音频文件为空")
        return None
        
    # 记录成功信息到日志
    file_size_mb = file_size / (1024 * 1024)  # MB
    logger.info(f"音频提取成功: {audio_path}, 大小: {file_size_mb:.2f} MB")
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


def separate_audio_sources(audio_path: str, video_name: str, work_dir: str) -> tuple[Optional[str], Optional[str]]:
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


def upload_audio_to_oss(local_audio_path: str, object_key: Optional[str] = None) -> Optional[str]:
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


def use_online_asr_service(oss_audio_url: str, subtitle_path: str):
    """
    使用DashScope在线语音识别服务
    
    Args:
        oss_audio_url: OSS音频文件URL
        subtitle_path: 字幕文件保存路径
    
    Returns:
        返回阿里云格式的字幕内容
    """
    # 配置API Key
    dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY')
    logger.info(f"使用OSS音频URL进行语音识别: {oss_audio_url}")
    
    # 提交异步识别任务
    task_response = dashscope.audio.asr.Transcription.async_call(
        model='paraformer-v2',
        file_urls=[oss_audio_url],
        language_hints=['yue', "zh"],  # 支持粤语和中文
        timestamp_alignment_enabled=True  # 启用时间戳对齐
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