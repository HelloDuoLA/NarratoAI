import os
import re
import json
import traceback
import edge_tts
import asyncio
from loguru import logger
from typing import List, Union
from datetime import datetime
from xml.sax.saxutils import unescape
from edge_tts import submaker, SubMaker
from edge_tts.submaker import mktimestamp
from moviepy.video.tools import subtitles
import time
import requests

from app.config import config
from app.utils import utils


def download_subtitle_file(download_url: str, text: str) -> str:
    """
    下载字幕文件到指定目录
    
    :param download_url: 字幕文件下载地址
    :param text: 原始文本，用于生成文件名
    :return: 下载后的文件路径
    """
    try:
        # 创建目标目录
        tts_tmp_dir = "/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/NarratoAI/resource/tts_tmp"
        os.makedirs(tts_tmp_dir, exist_ok=True)
        
        # 生成文件名（基于文本内容的hash + 时间戳）
        import hashlib
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()[:8]
        timestamp = int(time.time())
        filename = f"subtitle_{text_hash}_{timestamp}.json"
        
        file_path = os.path.join(tts_tmp_dir, filename)
        
        # 下载文件
        logger.info(f"开始下载字幕文件: {download_url}")
        response = requests.get(download_url, timeout=30)
        response.raise_for_status()
        
        # 保存文件
        with open(file_path, 'wb') as f:
            f.write(response.content)
        
        logger.success(f"字幕文件下载成功: {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"下载字幕文件失败: {str(e)}")
        return ""


def create_submaker_from_minimax_subtitle(subtitle_file_path: str) -> Union[SubMaker, None]:
    """
    从MiniMax下载的字幕文件创建SubMaker对象
    
    :param subtitle_file_path: 字幕文件路径
    :return: SubMaker对象
    """
    try:
        sub_maker = SubMaker()
        
        with open(subtitle_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析JSON格式（MiniMax格式）
        try:
            subtitle_data = json.loads(content)
            if isinstance(subtitle_data, list):
                # MiniMax JSON格式
                for item in subtitle_data:
                    text = item.get('text', '').strip()
                    time_begin = item.get('time_begin', 0)  # 毫秒
                    time_end = item.get('time_end', 0)      # 毫秒
                    
                    if text:
                        # 将毫秒转换为10纳秒单位 (1毫秒 = 10000个10纳秒单位)
                        start_offset = int(time_begin * 10000)
                        end_offset = int(time_end * 10000)
                        
                        sub_maker.subs.append(text)
                        sub_maker.offset.append((start_offset, end_offset))
                
                logger.success(f"成功解析MiniMax JSON字幕文件，共 {len(sub_maker.subs)} 条字幕")
                return sub_maker
            else:
                logger.error("JSON格式不正确，期望为数组格式")
                return None
        
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {str(e)}")
            return None
            
        return sub_maker
        
    except Exception as e:
        logger.error(f"解析字幕文件失败: {str(e)}")
        return None


def parse_voice_name(name: str):
    # zh-CN-XiaoyiNeural-Female
    # zh-CN-YunxiNeural-Male
    # zh-CN-XiaoxiaoMultilingualNeural-V2-Female
    name = name.replace("-Female", "").replace("-Male", "").strip()
    # name = name.replace("_minimax", "")
    return name


def is_azure_v2_voice(voice_name: str):
    voice_name = parse_voice_name(voice_name)
    if voice_name.endswith("-V2"):
        return voice_name.replace("-V2", "").strip()
    return ""

def is_minimax_voice(voice_name: str):
    return "minimax" in  voice_name.lower()

def tts(
    text: str, voice_name: str, voice_rate: float, voice_pitch: float, voice_file: str
) -> Union[SubMaker, None]:
    if is_azure_v2_voice(voice_name):
        return azure_tts_v2(text, voice_name, voice_file)
    elif is_minimax_voice(voice_name):
        return minimax_tts(text, voice_name, voice_file)
    return azure_tts_v1(text, voice_name, voice_rate, voice_pitch, voice_file)


def convert_rate_to_percent(rate: float) -> str:
    if rate == 1.0:
        return "+0%"
    percent = round((rate - 1.0) * 100)
    if percent > 0:
        return f"+{percent}%"
    else:
        return f"{percent}%"


def convert_pitch_to_percent(rate: float) -> str:
    if rate == 1.0:
        return "+0Hz"
    percent = round((rate - 1.0) * 100)
    if percent > 0:
        return f"+{percent}Hz"
    else:
        return f"{percent}Hz"


def azure_tts_v1(
    text: str, voice_name: str, voice_rate: float, voice_pitch: float, voice_file: str
) -> Union[SubMaker, None]:
    voice_name = parse_voice_name(voice_name)
    text = text.strip()
    rate_str = convert_rate_to_percent(voice_rate)
    pitch_str = convert_pitch_to_percent(voice_pitch)
    for i in range(3):
        try:
            logger.info(f"第 {i+1} 次使用 edge_tts 生成音频")

            async def _do() -> tuple[SubMaker, bytes]:
                communicate = edge_tts.Communicate(text, voice_name, rate=rate_str, pitch=pitch_str, proxy=config.proxy.get("http"))
                sub_maker = edge_tts.SubMaker()
                audio_data = bytes()  # 用于存储音频数据
                
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data += chunk["data"]
                    elif chunk["type"] == "WordBoundary":
                        sub_maker.create_sub(
                            (chunk["offset"], chunk["duration"]), chunk["text"]
                        )
                return sub_maker, audio_data

            # 获取音频数据和字幕信息
            sub_maker, audio_data = asyncio.run(_do())
            
            # 验证数据是否有效
            if not sub_maker or not sub_maker.subs or not audio_data:
                logger.warning(f"failed, invalid data generated")
                if i < 2:
                    time.sleep(1)
                continue

            # 数据有效，写入文件
            with open(voice_file, "wb") as file:
                file.write(audio_data)
            return sub_maker
        except Exception as e:
            logger.error(f"生成音频文件时出错: {str(e)}")
            if i < 2:
                time.sleep(1)
    return None

# TODO: 待完善
def minimax_tts(text: str, voice_name: str, voice_file: str) -> Union[SubMaker, None]:
    group_id = config.minimax.get("MINIMAX_GROUP_ID", "")
    api_key = config.minimax.get("MINIMAX_KEY", "")
            
    url = "https://api.minimaxi.com/v1/t2a_v2?GroupId=" + group_id

    # 构建TTS请求头
    def build_tts_headers() -> dict:
        headers = {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/json',
            'authorization': "Bearer " + api_key,
        }
        return headers

    # 构建TTS请求体
    def build_tts_body(text: str, config: dict) -> dict:
        body = json.dumps({
            "model":config["model"],
            "text":f"{text}",
            "stream":config["stream"],
            "language_boost": config["language_boost"],
            "subtitle_enable" : True,
            "voice_setting":{
                "voice_id":config["voice_id"],
                "speed":config["speed"],
                "vol":config["vol"],
                "pitch":config["pitch"],
                "emotion":config["emotion"]
            },
            "audio_setting":{
                "sample_rate":config["sample_rate"],
                "bitrate":config["bitrate"],
                "format":config["format"],
                "channel":config["channel"]
            }
        })
        return body
    
    model = config.minimax.get("select_model", "")
    language_boost = config.minimax.get("select_language", "")
    voice_name = voice_name.replace("_minimax", "")
    config_ = {
        "model" : model,
        "stream" : False,  # 是否使用流式
        "voice_id" : voice_name,  # 语音ID
        "speed" : 1.2,  # 语速
        "vol" : 1.0,  # 音量
        "pitch" : 0,  # 音调
        "emotion" : "neutral",  # 情感
        "sample_rate" : 44100,  # 采样率
        "bitrate" : 256000,  # 比特率
        "format" : 'mp3',  # 音频格式
        "channel" : 1,  # 声道数
        "language_boost" : language_boost
    }
        
    tts_headers = build_tts_headers()
    tts_body = build_tts_body(text, config_)
    
    
    for i in range(3):
        try:
            logger.info(f"start, voice name: {voice_name}, try: {i + 1}")
            response = requests.request("POST", url, stream=False, headers=tts_headers, data=tts_body)
            parsed_json = json.loads(response.text)
            base_resp = parsed_json['base_resp']
            extra_info = parsed_json['extra_info']
            if not check_minimax_code(base_resp['status_code']):
                print(f"base_resp['message']: {base_resp['message']}")
                raise Exception(f"Error: {base_resp['message']} extra_info:{extra_info}")
            # 获取audio字段的值
            audio_value = bytes.fromhex(parsed_json['data']['audio'])
            # 字幕 parsed_json['data']['subtitle_file'], 需要去下载
            zimu_download_path = parsed_json['data']['subtitle_file']
            
            # 下载字幕文件
            subtitle_file_path = download_subtitle_file(zimu_download_path, text)
            
            with open(voice_file, 'wb') as file:
                file.write(audio_value)
            # logger.info(f"音频保存路径: {voice_file}")

            # 处理字幕文件，创建SubMaker对象
            if subtitle_file_path:
                sub_maker = create_submaker_from_minimax_subtitle(subtitle_file_path)
                if sub_maker:
                    logger.success(f"MiniMax TTS 成功生成音频和字幕: {voice_file}")
                    return sub_maker
            
        except Exception as e:
            logger.error(f"failed, error: {str(e)}")
            if i < 2:  # 如果不是最后一次重试，则等待1秒
                time.sleep(3)
    
    # 所有重试都失败
    return None


def azure_tts_v2(text: str, voice_name: str, voice_file: str) -> Union[SubMaker, None]:
    voice_name = is_azure_v2_voice(voice_name)
    if not voice_name:
        logger.error(f"invalid voice name: {voice_name}")
        raise ValueError(f"invalid voice name: {voice_name}")
    text = text.strip()

    # 转为音频偏移量, 单位是10纳秒
    def _format_duration_to_offset(duration) -> int:
        if isinstance(duration, str):
            time_obj = datetime.strptime(duration, "%H:%M:%S.%f")
            milliseconds = (
                (time_obj.hour * 3600000)
                + (time_obj.minute * 60000)
                + (time_obj.second * 1000)
                + (time_obj.microsecond // 1000)
            )
            return milliseconds * 10000

        if isinstance(duration, int):
            return duration

        return 0

    for i in range(3):
        try:
            logger.info(f"start, voice name: {voice_name}, try: {i + 1}")

            import azure.cognitiveservices.speech as speechsdk

            sub_maker = SubMaker()
            # 构造submaker对象
            def speech_synthesizer_word_boundary_cb(evt: speechsdk.SessionEventArgs):
                duration = _format_duration_to_offset(str(evt.duration))
                offset = _format_duration_to_offset(evt.audio_offset)
                sub_maker.subs.append(evt.text)
                sub_maker.offset.append((offset, offset + duration))

            # Creates an instance of a speech config with specified subscription key and service region.
            speech_key = config.azure.get("speech_key", "")
            service_region = config.azure.get("speech_region", "")
            audio_config = speechsdk.audio.AudioOutputConfig(
                filename=voice_file, use_default_speaker=True
            )
            speech_config = speechsdk.SpeechConfig(
                subscription=speech_key, region=service_region
            )
            speech_config.speech_synthesis_voice_name = voice_name
            # speech_config.set_property(property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestSentenceBoundary,
            #                            value='true')
            speech_config.set_property(
                property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestWordBoundary,
                value="true",
            )

            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
            )
            speech_synthesizer = speechsdk.SpeechSynthesizer(
                audio_config=audio_config, speech_config=speech_config
            )
            speech_synthesizer.synthesis_word_boundary.connect(
                speech_synthesizer_word_boundary_cb
            )

            result = speech_synthesizer.speak_text_async(text).get()
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.success(f"azure v2 speech synthesis succeeded: {voice_file}")
                return sub_maker
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                logger.error(
                    f"azure v2 speech synthesis canceled: {cancellation_details.reason}"
                )
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    logger.error(
                        f"azure v2 speech synthesis error: {cancellation_details.error_details}"
                    )
            if i < 2:  # 如果不是最后一次重试，则等待1秒
                time.sleep(1)
            logger.info(f"completed, output file: {voice_file}")
        except Exception as e:
            logger.error(f"failed, error: {str(e)}")
            if i < 2:  # 如果不是最后一次重试，则等待1秒
                time.sleep(3)
    return None


def _format_text(text: str) -> str:
    text = text.replace("\n", " ")
    text = text.replace("\"", " ")
    text = text.replace("[", " ")
    text = text.replace("]", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("）", " ")
    text = text.replace("（", " ")
    text = text.replace("{", " ")
    text = text.replace("}", " ")
    text = text.strip()
    return text


def create_subtitle_from_multiple(text: str, sub_maker_list: List[SubMaker], list_script: List[dict], 
                                  subtitle_file: str):
    """
    根据多个 SubMaker 对象、完整文本和原始脚本创建优化的字幕文件
    1. 使用原始脚本中的时间戳
    2. 跳过 OST 为 true 的部分
    3. 将字幕文件按照标点符号分割成多行
    4. 根据完整文本分段，保持原文的语句结构
    5. 生成新的字幕文件，时间戳包含小时单位
    """
    text = _format_text(text)
    sentences = utils.split_string_by_punctuations(text)

    def formatter(idx: int, start_time: str, end_time: str, sub_text: str) -> str:
        return f"{idx}\n{start_time.replace('.', ',')} --> {end_time.replace('.', ',')}\n{sub_text}\n"

    sub_items = []
    sub_index = 0
    sentence_index = 0

    try:
        sub_maker_index = 0
        for script_item in list_script:
            if script_item['OST']:
                continue

            start_time, end_time = script_item['timestamp'].split('-')
            if sub_maker_index >= len(sub_maker_list):
                logger.error(f"Sub maker list index out of range: {sub_maker_index}")
                break
            sub_maker = sub_maker_list[sub_maker_index]
            sub_maker_index += 1

            script_duration = utils.time_to_seconds(end_time) - utils.time_to_seconds(start_time)
            audio_duration = get_audio_duration(sub_maker)
            time_ratio = script_duration / audio_duration if audio_duration > 0 else 1

            current_sub = ""
            current_start = None
            current_end = None

            for offset, sub in zip(sub_maker.offset, sub_maker.subs):
                sub = unescape(sub).strip()
                sub_start = utils.seconds_to_time(utils.time_to_seconds(start_time) + offset[0] / 10000000 * time_ratio)
                sub_end = utils.seconds_to_time(utils.time_to_seconds(start_time) + offset[1] / 10000000 * time_ratio)
                
                if current_start is None:
                    current_start = sub_start
                current_end = sub_end
                
                current_sub += sub
                
                # 检查当前累积的字幕是否匹配下一个句子
                while sentence_index < len(sentences) and sentences[sentence_index] in current_sub:
                    sub_index += 1
                    line = formatter(
                        idx=sub_index,
                        start_time=current_start,
                        end_time=current_end,
                        sub_text=sentences[sentence_index].strip(),
                    )
                    sub_items.append(line)
                    current_sub = current_sub.replace(sentences[sentence_index], "", 1).strip()
                    current_start = current_end
                    sentence_index += 1

                # 如果当前字幕长度超过15个字符，也生成一个新的字幕项
                if len(current_sub) > 15:
                    sub_index += 1
                    line = formatter(
                        idx=sub_index,
                        start_time=current_start,
                        end_time=current_end,
                        sub_text=current_sub.strip(),
                    )
                    sub_items.append(line)
                    current_sub = ""
                    current_start = current_end

            # 处理剩余的文本
            if current_sub.strip():
                sub_index += 1
                line = formatter(
                    idx=sub_index,
                    start_time=current_start,
                    end_time=current_end,
                    sub_text=current_sub.strip(),
                )
                sub_items.append(line)

        if len(sub_items) == 0:
            logger.error("No subtitle items generated")
            return

        with open(subtitle_file, "w", encoding="utf-8") as file:
            file.write("\n".join(sub_items))

        logger.info(f"completed, subtitle file created: {subtitle_file}")
    except Exception as e:
        logger.error(f"failed, error: {str(e)}")
        traceback.print_exc()


def create_subtitle(sub_maker: submaker.SubMaker, text: str, subtitle_file: str):
    """
    优化字幕文件
    1. 将字幕文件按照标点符号分割成多行
    2. 逐行匹配字幕文件中的文本
    3. 生成新的字幕文件
    """

    text = _format_text(text)

    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
        """
        1
        00:00:00,000 --> 00:00:02,360
        跑步是一项简单易行的运动
        """
        start_t = mktimestamp(start_time).replace(".", ",")
        end_t = mktimestamp(end_time).replace(".", ",")
        return f"{idx}\n" f"{start_t} --> {end_t}\n" f"{sub_text}\n"

    start_time = -1.0
    sub_items = []
    sub_index = 0

    script_lines = utils.split_string_by_punctuations(text)

    def match_line(_sub_line: str, _sub_index: int):
        if len(script_lines) <= _sub_index:
            return ""

        _line = script_lines[_sub_index]
        if _sub_line == _line:
            return script_lines[_sub_index].strip()

        _sub_line_ = re.sub(r"[^\w\s]", "", _sub_line)
        _line_ = re.sub(r"[^\w\s]", "", _line)
        if _sub_line_ == _line_:
            return _line_.strip()

        _sub_line_ = re.sub(r"\W+", "", _sub_line)
        _line_ = re.sub(r"\W+", "", _line)
        if _sub_line_ == _line_:
            return _line.strip()

        return ""

    sub_line = ""

    try:
        for _, (offset, sub) in enumerate(zip(sub_maker.offset, sub_maker.subs)):
            _start_time, end_time = offset
            if start_time < 0:
                start_time = _start_time

            sub = unescape(sub)
            sub_line += sub
            sub_text = match_line(sub_line, sub_index)
            if sub_text:
                sub_index += 1
                line = formatter(
                    idx=sub_index,
                    start_time=start_time,
                    end_time=end_time,
                    sub_text=sub_text,
                )
                sub_items.append(line)
                start_time = -1.0
                sub_line = ""

        if len(sub_items) == len(script_lines):
            with open(subtitle_file, "w", encoding="utf-8") as file:
                file.write("\n".join(sub_items) + "\n")
            try:
                sbs = subtitles.file_to_subtitles(subtitle_file, encoding="utf-8")
                duration = max([tb for ((ta, tb), txt) in sbs])
                logger.info(
                    f"已创建字幕文件: {subtitle_file}, duration: {duration}"
                )
                return subtitle_file, duration
            except Exception as e:
                logger.error(f"failed, error: {str(e)}")
                os.remove(subtitle_file)
        else:
            logger.error(
                f"字幕创建失败, 字幕长度: {len(sub_items)}, script_lines len: {len(script_lines)}"
                f"\nsub_items:{json.dumps(sub_items, indent=4, ensure_ascii=False)}"
                f"\nscript_lines:{json.dumps(script_lines, indent=4, ensure_ascii=False)}"
            )

    except Exception as e:
        logger.error(f"failed, error: {str(e)}")


def get_audio_duration(sub_maker: submaker.SubMaker):
    """
    获取音频时长
    """
    if not sub_maker.offset:
        return 0.0
    return sub_maker.offset[-1][1] / 10000000

# 直接被生成视频调用的函数
def tts_multiple(task_id: str, list_script: list, voice_name: str, voice_rate: float, voice_pitch: float, enable_subtitles: bool):
    """
    根据JSON文件中的多段文本进行TTS转换
    
    :param task_id: 任务ID
    :param list_script: 脚本列表
    :param voice_name: 语音名称
    :param voice_rate: 语音速率
    :return: 生成的音频文件列表
    """
    voice_name = parse_voice_name(voice_name)
    output_dir = utils.task_dir(task_id)
    tts_results = []
    
    # 对每一个片段
    for item in list_script:
        if item['OST'] != 1:
            # 将时间戳中的冒号替换为下划线
            timestamp = item['timestamp'].replace(':', '_')
            audio_file = os.path.join(output_dir, f"audio_{timestamp}.mp3")
            subtitle_file = os.path.join(output_dir, f"subtitle_{timestamp}.srt")

            text = item['narration']

            sub_maker = tts(
                text=text,
                voice_name=voice_name,
                voice_rate=voice_rate,
                voice_pitch=voice_pitch,
                voice_file=audio_file,
            )

            if sub_maker is None:
                logger.error(f"无法为时间戳 {timestamp} 生成音频; "
                             f"如果您在中国，请使用VPN; "
                             f"或者使用其他 tts 引擎")
                continue
            else:
                if enable_subtitles:
                # 为当前片段生成字幕文件
                    subtitle_result = create_subtitle(sub_maker=sub_maker, text=text, subtitle_file=subtitle_file)
                    if subtitle_result is not None:
                        _, duration = subtitle_result
                    else:
                        duration = get_audio_duration(sub_maker)
                        logger.warning(f"字幕生成失败，使用音频时长作为默认值: {duration}")
                else:
                    logger.info(f"字幕生成被禁用，使用音频时长")
                    # subtitle_file = None
                    duration = get_audio_duration(sub_maker)
                    

            tts_results.append({
                "_id": item['_id'],
                "timestamp": item['timestamp'],
                "audio_file": audio_file,
                "subtitle_file": subtitle_file,
                "duration": duration,
                "text": text,
            })
            logger.info(f"已生成音频文件: {audio_file}")

    return tts_results


def get_all_azure_voices(filter_locals=None) -> list[str]:
    if filter_locals is None:
        filter_locals = ["zh-CN", "en-US", "zh-HK", "zh-TW", "vi-VN"]
    voices_str = """
Name: af-ZA-AdriNeural
Gender: Female

Name: af-ZA-WillemNeural
Gender: Male

Name: am-ET-AmehaNeural
Gender: Male

Name: am-ET-MekdesNeural
Gender: Female

Name: ar-AE-FatimaNeural
Gender: Female

Name: ar-AE-HamdanNeural
Gender: Male

Name: ar-BH-AliNeural
Gender: Male

Name: ar-BH-LailaNeural
Gender: Female

Name: ar-DZ-AminaNeural
Gender: Female

Name: ar-DZ-IsmaelNeural
Gender: Male

Name: ar-EG-SalmaNeural
Gender: Female

Name: ar-EG-ShakirNeural
Gender: Male

Name: ar-IQ-BasselNeural
Gender: Male

Name: ar-IQ-RanaNeural
Gender: Female

Name: ar-JO-SanaNeural
Gender: Female

Name: ar-JO-TaimNeural
Gender: Male

Name: ar-KW-FahedNeural
Gender: Male

Name: ar-KW-NouraNeural
Gender: Female

Name: ar-LB-LaylaNeural
Gender: Female

Name: ar-LB-RamiNeural
Gender: Male

Name: ar-LY-ImanNeural
Gender: Female

Name: ar-LY-OmarNeural
Gender: Male

Name: ar-MA-JamalNeural
Gender: Male

Name: ar-MA-MounaNeural
Gender: Female

Name: ar-OM-AbdullahNeural
Gender: Male

Name: ar-OM-AyshaNeural
Gender: Female

Name: ar-QA-AmalNeural
Gender: Female

Name: ar-QA-MoazNeural
Gender: Male

Name: ar-SA-HamedNeural
Gender: Male

Name: ar-SA-ZariyahNeural
Gender: Female

Name: ar-SY-AmanyNeural
Gender: Female

Name: ar-SY-LaithNeural
Gender: Male

Name: ar-TN-HediNeural
Gender: Male

Name: ar-TN-ReemNeural
Gender: Female

Name: ar-YE-MaryamNeural
Gender: Female

Name: ar-YE-SalehNeural
Gender: Male

Name: az-AZ-BabekNeural
Gender: Male

Name: az-AZ-BanuNeural
Gender: Female

Name: bg-BG-BorislavNeural
Gender: Male

Name: bg-BG-KalinaNeural
Gender: Female

Name: bn-BD-NabanitaNeural
Gender: Female

Name: bn-BD-PradeepNeural
Gender: Male

Name: bn-IN-BashkarNeural
Gender: Male

Name: bn-IN-TanishaaNeural
Gender: Female

Name: bs-BA-GoranNeural
Gender: Male

Name: bs-BA-VesnaNeural
Gender: Female

Name: ca-ES-EnricNeural
Gender: Male

Name: ca-ES-JoanaNeural
Gender: Female

Name: cs-CZ-AntoninNeural
Gender: Male

Name: cs-CZ-VlastaNeural
Gender: Female

Name: cy-GB-AledNeural
Gender: Male

Name: cy-GB-NiaNeural
Gender: Female

Name: da-DK-ChristelNeural
Gender: Female

Name: da-DK-JeppeNeural
Gender: Male

Name: de-AT-IngridNeural
Gender: Female

Name: de-AT-JonasNeural
Gender: Male

Name: de-CH-JanNeural
Gender: Male

Name: de-CH-LeniNeural
Gender: Female

Name: de-DE-AmalaNeural
Gender: Female

Name: de-DE-ConradNeural
Gender: Male

Name: de-DE-FlorianMultilingualNeural
Gender: Male

Name: de-DE-KatjaNeural
Gender: Female

Name: de-DE-KillianNeural
Gender: Male

Name: de-DE-SeraphinaMultilingualNeural
Gender: Female

Name: el-GR-AthinaNeural
Gender: Female

Name: el-GR-NestorasNeural
Gender: Male

Name: en-AU-NatashaNeural
Gender: Female

Name: en-AU-WilliamNeural
Gender: Male

Name: en-CA-ClaraNeural
Gender: Female

Name: en-CA-LiamNeural
Gender: Male

Name: en-GB-LibbyNeural
Gender: Female

Name: en-GB-MaisieNeural
Gender: Female

Name: en-GB-RyanNeural
Gender: Male

Name: en-GB-SoniaNeural
Gender: Female

Name: en-GB-ThomasNeural
Gender: Male

Name: en-HK-SamNeural
Gender: Male

Name: en-HK-YanNeural
Gender: Female

Name: en-IE-ConnorNeural
Gender: Male

Name: en-IE-EmilyNeural
Gender: Female

Name: en-IN-NeerjaExpressiveNeural
Gender: Female

Name: en-IN-NeerjaNeural
Gender: Female

Name: en-IN-PrabhatNeural
Gender: Male

Name: en-KE-AsiliaNeural
Gender: Female

Name: en-KE-ChilembaNeural
Gender: Male

Name: en-NG-AbeoNeural
Gender: Male

Name: en-NG-EzinneNeural
Gender: Female

Name: en-NZ-MitchellNeural
Gender: Male

Name: en-NZ-MollyNeural
Gender: Female

Name: en-PH-JamesNeural
Gender: Male

Name: en-PH-RosaNeural
Gender: Female

Name: en-SG-LunaNeural
Gender: Female

Name: en-SG-WayneNeural
Gender: Male

Name: en-TZ-ElimuNeural
Gender: Male

Name: en-TZ-ImaniNeural
Gender: Female

Name: en-US-AnaNeural
Gender: Female

Name: en-US-AndrewNeural
Gender: Male

Name: en-US-AriaNeural
Gender: Female

Name: en-US-AvaNeural
Gender: Female

Name: en-US-BrianNeural
Gender: Male

Name: en-US-ChristopherNeural
Gender: Male

Name: en-US-EmmaNeural
Gender: Female

Name: en-US-EricNeural
Gender: Male

Name: en-US-GuyNeural
Gender: Male

Name: en-US-JennyNeural
Gender: Female

Name: en-US-MichelleNeural
Gender: Female

Name: en-US-RogerNeural
Gender: Male

Name: en-US-SteffanNeural
Gender: Male

Name: en-ZA-LeahNeural
Gender: Female

Name: en-ZA-LukeNeural
Gender: Male

Name: es-AR-ElenaNeural
Gender: Female

Name: es-AR-TomasNeural
Gender: Male

Name: es-BO-MarceloNeural
Gender: Male

Name: es-BO-SofiaNeural
Gender: Female

Name: es-CL-CatalinaNeural
Gender: Female

Name: es-CL-LorenzoNeural
Gender: Male

Name: es-CO-GonzaloNeural
Gender: Male

Name: es-CO-SalomeNeural
Gender: Female

Name: es-CR-JuanNeural
Gender: Male

Name: es-CR-MariaNeural
Gender: Female

Name: es-CU-BelkysNeural
Gender: Female

Name: es-CU-ManuelNeural
Gender: Male

Name: es-DO-EmilioNeural
Gender: Male

Name: es-DO-RamonaNeural
Gender: Female

Name: es-EC-AndreaNeural
Gender: Female

Name: es-EC-LuisNeural
Gender: Male

Name: es-ES-AlvaroNeural
Gender: Male

Name: es-ES-ElviraNeural
Gender: Female

Name: es-ES-XimenaNeural
Gender: Female

Name: es-GQ-JavierNeural
Gender: Male

Name: es-GQ-TeresaNeural
Gender: Female

Name: es-GT-AndresNeural
Gender: Male

Name: es-GT-MartaNeural
Gender: Female

Name: es-HN-CarlosNeural
Gender: Male

Name: es-HN-KarlaNeural
Gender: Female

Name: es-MX-DaliaNeural
Gender: Female

Name: es-MX-JorgeNeural
Gender: Male

Name: es-NI-FedericoNeural
Gender: Male

Name: es-NI-YolandaNeural
Gender: Female

Name: es-PA-MargaritaNeural
Gender: Female

Name: es-PA-RobertoNeural
Gender: Male

Name: es-PE-AlexNeural
Gender: Male

Name: es-PE-CamilaNeural
Gender: Female

Name: es-PR-KarinaNeural
Gender: Female

Name: es-PR-VictorNeural
Gender: Male

Name: es-PY-MarioNeural
Gender: Male

Name: es-PY-TaniaNeural
Gender: Female

Name: es-SV-LorenaNeural
Gender: Female

Name: es-SV-RodrigoNeural
Gender: Male

Name: es-US-AlonsoNeural
Gender: Male

Name: es-US-PalomaNeural
Gender: Female

Name: es-UY-MateoNeural
Gender: Male

Name: es-UY-ValentinaNeural
Gender: Female

Name: es-VE-PaolaNeural
Gender: Female

Name: es-VE-SebastianNeural
Gender: Male

Name: et-EE-AnuNeural
Gender: Female

Name: et-EE-KertNeural
Gender: Male

Name: fa-IR-DilaraNeural
Gender: Female

Name: fa-IR-FaridNeural
Gender: Male

Name: fi-FI-HarriNeural
Gender: Male

Name: fi-FI-NooraNeural
Gender: Female

Name: fil-PH-AngeloNeural
Gender: Male

Name: fil-PH-BlessicaNeural
Gender: Female

Name: fr-BE-CharlineNeural
Gender: Female

Name: fr-BE-GerardNeural
Gender: Male

Name: fr-CA-AntoineNeural
Gender: Male

Name: fr-CA-JeanNeural
Gender: Male

Name: fr-CA-SylvieNeural
Gender: Female

Name: fr-CA-ThierryNeural
Gender: Male

Name: fr-CH-ArianeNeural
Gender: Female

Name: fr-CH-FabriceNeural
Gender: Male

Name: fr-FR-DeniseNeural
Gender: Female

Name: fr-FR-EloiseNeural
Gender: Female

Name: fr-FR-HenriNeural
Gender: Male

Name: fr-FR-RemyMultilingualNeural
Gender: Male

Name: fr-FR-VivienneMultilingualNeural
Gender: Female

Name: ga-IE-ColmNeural
Gender: Male

Name: ga-IE-OrlaNeural
Gender: Female

Name: gl-ES-RoiNeural
Gender: Male

Name: gl-ES-SabelaNeural
Gender: Female

Name: gu-IN-DhwaniNeural
Gender: Female

Name: gu-IN-NiranjanNeural
Gender: Male

Name: he-IL-AvriNeural
Gender: Male

Name: he-IL-HilaNeural
Gender: Female

Name: hi-IN-MadhurNeural
Gender: Male

Name: hi-IN-SwaraNeural
Gender: Female

Name: hr-HR-GabrijelaNeural
Gender: Female

Name: hr-HR-SreckoNeural
Gender: Male

Name: hu-HU-NoemiNeural
Gender: Female

Name: hu-HU-TamasNeural
Gender: Male

Name: id-ID-ArdiNeural
Gender: Male

Name: id-ID-GadisNeural
Gender: Female

Name: is-IS-GudrunNeural
Gender: Female

Name: is-IS-GunnarNeural
Gender: Male

Name: it-IT-DiegoNeural
Gender: Male

Name: it-IT-ElsaNeural
Gender: Female

Name: it-IT-GiuseppeNeural
Gender: Male

Name: it-IT-IsabellaNeural
Gender: Female

Name: ja-JP-KeitaNeural
Gender: Male

Name: ja-JP-NanamiNeural
Gender: Female

Name: jv-ID-DimasNeural
Gender: Male

Name: jv-ID-SitiNeural
Gender: Female

Name: ka-GE-EkaNeural
Gender: Female

Name: ka-GE-GiorgiNeural
Gender: Male

Name: kk-KZ-AigulNeural
Gender: Female

Name: kk-KZ-DauletNeural
Gender: Male

Name: km-KH-PisethNeural
Gender: Male

Name: km-KH-SreymomNeural
Gender: Female

Name: kn-IN-GaganNeural
Gender: Male

Name: kn-IN-SapnaNeural
Gender: Female

Name: ko-KR-HyunsuNeural
Gender: Male

Name: ko-KR-InJoonNeural
Gender: Male

Name: ko-KR-SunHiNeural
Gender: Female

Name: lo-LA-ChanthavongNeural
Gender: Male

Name: lo-LA-KeomanyNeural
Gender: Female

Name: lt-LT-LeonasNeural
Gender: Male

Name: lt-LT-OnaNeural
Gender: Female

Name: lv-LV-EveritaNeural
Gender: Female

Name: lv-LV-NilsNeural
Gender: Male

Name: mk-MK-AleksandarNeural
Gender: Male

Name: mk-MK-MarijaNeural
Gender: Female

Name: ml-IN-MidhunNeural
Gender: Male

Name: ml-IN-SobhanaNeural
Gender: Female

Name: mn-MN-BataaNeural
Gender: Male

Name: mn-MN-YesuiNeural
Gender: Female

Name: mr-IN-AarohiNeural
Gender: Female

Name: mr-IN-ManoharNeural
Gender: Male

Name: ms-MY-OsmanNeural
Gender: Male

Name: ms-MY-YasminNeural
Gender: Female

Name: mt-MT-GraceNeural
Gender: Female

Name: mt-MT-JosephNeural
Gender: Male

Name: my-MM-NilarNeural
Gender: Female

Name: my-MM-ThihaNeural
Gender: Male

Name: nb-NO-FinnNeural
Gender: Male

Name: nb-NO-PernilleNeural
Gender: Female

Name: ne-NP-HemkalaNeural
Gender: Female

Name: ne-NP-SagarNeural
Gender: Male

Name: nl-BE-ArnaudNeural
Gender: Male

Name: nl-BE-DenaNeural
Gender: Female

Name: nl-NL-ColetteNeural
Gender: Female

Name: nl-NL-FennaNeural
Gender: Female

Name: nl-NL-MaartenNeural
Gender: Male

Name: pl-PL-MarekNeural
Gender: Male

Name: pl-PL-ZofiaNeural
Gender: Female

Name: ps-AF-GulNawazNeural
Gender: Male

Name: ps-AF-LatifaNeural
Gender: Female

Name: pt-BR-AntonioNeural
Gender: Male

Name: pt-BR-FranciscaNeural
Gender: Female

Name: pt-BR-ThalitaNeural
Gender: Female

Name: pt-PT-DuarteNeural
Gender: Male

Name: pt-PT-RaquelNeural
Gender: Female

Name: ro-RO-AlinaNeural
Gender: Female

Name: ro-RO-EmilNeural
Gender: Male

Name: ru-RU-DmitryNeural
Gender: Male

Name: ru-RU-SvetlanaNeural
Gender: Female

Name: si-LK-SameeraNeural
Gender: Male

Name: si-LK-ThiliniNeural
Gender: Female

Name: sk-SK-LukasNeural
Gender: Male

Name: sk-SK-ViktoriaNeural
Gender: Female

Name: sl-SI-PetraNeural
Gender: Female

Name: sl-SI-RokNeural
Gender: Male

Name: so-SO-MuuseNeural
Gender: Male

Name: so-SO-UbaxNeural
Gender: Female

Name: sq-AL-AnilaNeural
Gender: Female

Name: sq-AL-IlirNeural
Gender: Male

Name: sr-RS-NicholasNeural
Gender: Male

Name: sr-RS-SophieNeural
Gender: Female

Name: su-ID-JajangNeural
Gender: Male

Name: su-ID-TutiNeural
Gender: Female

Name: sv-SE-MattiasNeural
Gender: Male

Name: sv-SE-SofieNeural
Gender: Female

Name: sw-KE-RafikiNeural
Gender: Male

Name: sw-KE-ZuriNeural
Gender: Female

Name: sw-TZ-DaudiNeural
Gender: Male

Name: sw-TZ-RehemaNeural
Gender: Female

Name: ta-IN-PallaviNeural
Gender: Female

Name: ta-IN-ValluvarNeural
Gender: Male

Name: ta-LK-KumarNeural
Gender: Male

Name: ta-LK-SaranyaNeural
Gender: Female

Name: ta-MY-KaniNeural
Gender: Female

Name: ta-MY-SuryaNeural
Gender: Male

Name: ta-SG-AnbuNeural
Gender: Male

Name: ta-SG-VenbaNeural
Gender: Female

Name: te-IN-MohanNeural
Gender: Male

Name: te-IN-ShrutiNeural
Gender: Female

Name: th-TH-NiwatNeural
Gender: Male

Name: th-TH-PremwadeeNeural
Gender: Female

Name: tr-TR-AhmetNeural
Gender: Male

Name: tr-TR-EmelNeural
Gender: Female

Name: uk-UA-OstapNeural
Gender: Male

Name: uk-UA-PolinaNeural
Gender: Female

Name: ur-IN-GulNeural
Gender: Female

Name: ur-IN-SalmanNeural
Gender: Male

Name: ur-PK-AsadNeural
Gender: Male

Name: ur-PK-UzmaNeural
Gender: Female

Name: uz-UZ-MadinaNeural
Gender: Female

Name: uz-UZ-SardorNeural
Gender: Male

Name: vi-VN-HoaiMyNeural
Gender: Female

Name: vi-VN-NamMinhNeural
Gender: Male

Name: zh-CN-XiaoxiaoNeural
Gender: Female

Name: zh-CN-XiaoyiNeural
Gender: Female

Name: zh-CN-YunjianNeural
Gender: Male

Name: zh-CN-YunxiNeural
Gender: Male

Name: zh-CN-YunxiaNeural
Gender: Male

Name: zh-CN-YunyangNeural
Gender: Male

Name: zh-CN-liaoning-XiaobeiNeural
Gender: Female

Name: zh-CN-shaanxi-XiaoniNeural
Gender: Female

Name: zh-HK-HiuGaaiNeural
Gender: Female

Name: zh-HK-HiuMaanNeural
Gender: Female

Name: zh-HK-WanLungNeural
Gender: Male

Name: zh-TW-HsiaoChenNeural
Gender: Female

Name: zh-TW-HsiaoYuNeural
Gender: Female

Name: zh-TW-YunJheNeural
Gender: Male

Name: zu-ZA-ThandoNeural
Gender: Female

Name: zu-ZA-ThembaNeural
Gender: Male


Name: en-US-AvaMultilingualNeural-V2
Gender: Female

Name: en-US-AndrewMultilingualNeural-V2
Gender: Male

Name: en-US-EmmaMultilingualNeural-V2
Gender: Female

Name: en-US-BrianMultilingualNeural-V2
Gender: Male

Name: de-DE-FlorianMultilingualNeural-V2
Gender: Male

Name: de-DE-SeraphinaMultilingualNeural-V2
Gender: Female

Name: fr-FR-RemyMultilingualNeural-V2
Gender: Male

Name: fr-FR-VivienneMultilingualNeural-V2
Gender: Female

Name: zh-CN-XiaoxiaoMultilingualNeural-V2
Gender: Female

Name: zh-CN-YunxiNeural-V2
Gender: Male
    """.strip()
    voices = []
    name = ""
    for line in voices_str.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("Name: "):
            name = line[6:].strip()
        if line.startswith("Gender: "):
            gender = line[8:].strip()
            if name and gender:
                # voices.append({
                #     "name": name,
                #     "gender": gender,
                # })
                if filter_locals:
                    for filter_local in filter_locals:
                        if name.lower().startswith(filter_local.lower()):
                            voices.append(f"{name}-{gender}")
                else:
                    voices.append(f"{name}-{gender}")
                name = ""
    voices.sort()
    return voices

def check_minimax_code(error_code: int) -> bool:
    """
    检查错误码是否为0，并打印错误原因和解决办法
    :param error_code: 错误码
    :return: True if error_code is 0, else False
    """
    error_map = {
        1000: ("未知错误/系统默认错误", "请稍后再试"),
        1001: ("请求超时", "请稍后再试"),
        1002: ("请求频率超限", "请稍后再试"),
        1004: ("未授权/Token不匹配/Cookie缺失", "请检查API Key"),
        1008: ("余额不足", "请检查您的账户余额"),
        1024: ("内部错误", "请稍后再试"),
        1026: ("输入内容涉敏", "请调整输入内容"),
        1027: ("输出内容涉敏", "请调整输入内容"),
        1033: ("系统错误/下游服务错误", "请稍后再试"),
        1039: ("Token限制", "请调整max_tokens"),
        1041: ("连接数限制", "请联系我们"),
        1042: ("不可见字符比例超限/非法字符超过10%", "请检查输入内容，是否包含不可见字符或非法字符"),
        1043: ("ASR相似度检查失败", "请检查file_id与text_validation匹配度"),
        1044: ("克隆提示词相似度检查失败", "请检查克隆提示音频和提示词"),
        2013: ("参数错误", "请检查请求参数"),
        20132: ("语音克隆样本或voice_id参数错误", "请检查Voice Cloning 接口下的 file_id 和 T2A v2，T2A Large v2 接口下的 voice_id 参数"),
        2037: ("语音时长不符合要求(太长或太短)", "请检查voice_clone file_id文件时长，最少应不低于10秒，最长应不超过5分钟"),
        2038: ("用户语音克隆功能被禁用", "使用语音克隆功能需要完成账户身份认证，请根据您的使用需求在账户系管理》账户信息中进行个人或企业认证"),
        2039: ("语音克隆voice_id重复", "请修改voice_id，确保未和已有voice_id重复"),
        2042: ("无权访问该voice_id", "请确认是否为该voice_id创建者"),
        2045: ("请求频率增长超限", "请避免请求骤增骤减情况"),
        2048: ("语音克隆提示音频太长", "请调整prompt_audio音频文件时长（＜8s）"),
        2049: ("无效的API Key", "请检查API Key"),
    }
    if error_code == 0:
        return True
    else:
        reason, solution = error_map.get(
            error_code, ("未知错误码", "请参考文档或联系技术支持")
        )
        print(f"错误码: {error_code}\n原因: {reason}\n解决办法: {solution}")
        return False