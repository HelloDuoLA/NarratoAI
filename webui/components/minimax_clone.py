'''
这个文件是进行minimax音色复刻的
'''
import json
import requests
from dotenv import load_dotenv
import os
import streamlit as st
from loguru import logger

# 定义API基础URL
base_url = 'https://api.minimaxi.com/v1'

def upload_audio_file(config, file_path, purpose):
    """
    上传音频文件到MiniMax API
    
    Args:
        file_path (str): 音频文件路径
        purpose (str): 文件用途 ('voice_clone' 或 'prompt_audio')
    
    Returns:
        str: 上传文件的ID
    """
    group_id = config.minimax.get("MINIMAX_GROUP_ID", "")
    api_key = config.minimax.get("MINIMAX_KEY", "")

    url = f'{base_url}/files/upload?GroupId={group_id}'
    headers = {
        'authority': 'api.minimaxi.com',
        'Authorization': f'Bearer {api_key}'
    }
    
    data = {
        'purpose': purpose
    }
    
    with open(file_path, 'rb') as audio_file:
        files = {
            'file': audio_file
        }
        response = requests.post(url, headers=headers, data=data, files=files)
        response.raise_for_status()  # 如果请求失败会抛出异常
        try:
            file_id = response.json().get("file").get("file_id")
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            raise
        logger.info(f"Uploaded {file_path} (purpose: {purpose}) with file_id: {file_id}")
        return file_id
    

def clone_voice(config, clone_file_id, voice_id):
    """
    使用上传的音频文件进行声音复刻
    
    Args:
        clone_file_id (str): 用于声音复刻的音频文件ID
        voice_id (str): 要创建的声音ID
    
    Returns:
        dict: API响应结果
    """
    group_id= config.minimax.get("MINIMAX_GROUP_ID", "")
    api_key = config.minimax.get("MINIMAX_KEY", "")
    url = f'{base_url}/voice_clone?GroupId={group_id}'
    payload = json.dumps({
        "file_id": clone_file_id,
        "voice_id": voice_id,
        "text": '''我介绍一下我自己。
                我系深圳人，深圳出生长大，屋企人系用白话交流的。
                以前，我们喺深圳读书，朋友之间都系讲白话。
                不知几时开始，白话喺深圳已经不Work了。
                我身边嘅朋友大多数都系讲普通话。
                ''',
        "model": "speech-01-hd",
        # "need_noise_reduction": True,
        "need_volume_normalization": False,
        "language boost": "Chinese,Yue"
    })
    headers = {
        'Authorization': f'Bearer {api_key}',
        'content-type': 'application/json'
    }
    
    response = requests.post(url, headers=headers, data=payload)
    response.raise_for_status()
    result = response.json()
    logger.info(f"Voice clone result: {result}")
    return result

def clone_voice_minimax(config: dict, file_path: str, voice_id: str):
    clone_audio_file_id = upload_audio_file(config, file_path, 'voice_clone')
    return clone_voice(config, clone_audio_file_id, voice_id)

# 主流程
if __name__ == "__main__":
    # 上传用于声音复刻的音频
    clone_audio_file_id = upload_audio_file("/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/audio/demo_15s_clip_20250729_152828.wav", 'voice_clone')
    
    # 上传示例音频
    # prompt_audio_file_id = upload_audio_file('prompt.mp3', 'prompt_audio')
    
    # 执行声音复刻
    clone_voice(clone_audio_file_id, "shantou3")
    
