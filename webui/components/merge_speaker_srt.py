#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将阿里云语音识别结果转换为SRT字幕格式（针对大模型理解优化）
此脚本会合并相同说话人的字幕，以减少字幕段数，方便大模型理解，减少调用次数
"""

import json
import os
from typing import List, Dict, Tuple


def milliseconds_to_srt_time(ms: int) -> str:
    """
    将毫秒转换为SRT时间格式 (HH:MM:SS,mmm)
    """
    seconds = ms // 1000
    milliseconds = ms % 1000
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def merge_sentences_for_llm(json_data: Dict, max_duration_ms: int = 20000) -> List[Dict]:
    """
    合并相同说话人的相邻字幕，以便大模型理解
    
    Args:
        json_data: 阿里云语音转文字的JSON数据
        max_duration_ms: 合并后字幕的最大时长（毫秒），默认20秒
        
    Returns:
        合并后的字幕列表
    """
    merged_sentences = []
    
    for transcript in json_data.get("transcripts", []):
        sentences = transcript.get("sentences", [])
        if not sentences:
            continue
            
        # 初始化第一个句子
        current_merged = {
            "begin_time": sentences[0].get("begin_time", 0),
            "end_time": sentences[0].get("end_time", 0),
            "speaker_id": sentences[0].get("speaker_id", 0),
            "text": sentences[0].get("text", "")
        }
        
        # 遍历剩余句子
        for i in range(1, len(sentences)):
            sentence = sentences[i]
            speaker_id = sentence.get("speaker_id", 0)
            begin_time = sentence.get("begin_time", 0)
            end_time = sentence.get("end_time", 0)
            text = sentence.get("text", "")
            
            # 检查是否可以合并
            # 1. 说话人相同
            # 2. 合并后时长不超过max_duration_ms
            # 3. 当前句子与前一句之间没有太长的空白（判断空白时长是否可能是BGM）
            duration_if_merged = end_time - current_merged["begin_time"]
            gap_to_previous = begin_time - current_merged["end_time"]
            
            if (speaker_id == current_merged["speaker_id"] and 
                duration_if_merged <= max_duration_ms and
                gap_to_previous < 5000):  # 如果间隔超过5秒，可能是BGM，不合并
                # 合并句子
                current_merged["end_time"] = end_time
                current_merged["text"] += " " + text
            else:
                # 不能合并，保存当前合并的句子
                merged_sentences.append(current_merged)
                
                # 开始新的合并句子
                current_merged = {
                    "begin_time": begin_time,
                    "end_time": end_time,
                    "speaker_id": speaker_id,
                    "text": text
                }
        
        # 添加最后一个合并的句子
        merged_sentences.append(current_merged)
    
    return merged_sentences


def add_empty_subtitle_entries(sentences: List[Dict], min_gap_for_empty: int = 3000) -> List[Dict]:
    """
    在长时间空白处添加[无字幕]标识
    
    Args:
        sentences: 字幕句子列表
        min_gap_for_empty: 最小空白时长（毫秒），超过此时间则添加[无字幕]标识
        
    Returns:
        添加了[无字幕]标识的字幕列表
    """
    if not sentences:
        return sentences
    
    result = []
    
    # 添加第一个句子
    result.append(sentences[0])
    
    # 检查后续句子与前一句之间是否有长时间空白
    for i in range(1, len(sentences)):
        prev_sentence = sentences[i-1]
        curr_sentence = sentences[i]
        
        gap = curr_sentence["begin_time"] - prev_sentence["end_time"]
        
        # 如果空白时间超过阈值，添加[无字幕]标识
        if gap >= min_gap_for_empty:
            empty_entry = {
                "begin_time": prev_sentence["end_time"],
                "end_time": curr_sentence["begin_time"],
                "speaker_id": -1,  # 特殊标识表示无字幕
                "text": "[无字幕]"
            }
            result.append(empty_entry)
        
        result.append(curr_sentence)
    
    return result


def generate_srt_for_llm(json_data: Dict, max_duration_ms: int = 20000) -> str:
    """
    生成针对大模型理解优化的SRT字幕
    
    Args:
        json_data: 阿里云语音转文字的JSON数据
        max_duration_ms: 合并后字幕的最大时长（毫秒）
        
    Returns:
        SRT格式的字符串
    """
    # 合并相同说话人的相邻字幕
    merged_sentences = merge_sentences_for_llm(json_data, max_duration_ms)
    
    # 在长时间空白处添加[无字幕]标识
    final_sentences = add_empty_subtitle_entries(merged_sentences)
    
    # 生成SRT内容
    srt_content = []
    for i, sentence in enumerate(final_sentences, 1):
        begin_time = sentence["begin_time"]
        end_time = sentence["end_time"]
        speaker_id = sentence["speaker_id"]
        text = sentence["text"]
        
        srt_entry = []
        srt_entry.append(str(i))
        
        # 添加时间轴
        srt_entry.append(f"{milliseconds_to_srt_time(begin_time)} --> {milliseconds_to_srt_time(end_time)}")
        
        # 添加说话人标识和文本
        if speaker_id == -1:  # 无字幕标识
            srt_entry.append(text)
        else:
            srt_entry.append(f"[Speaker {speaker_id}]: {text}")
        
        srt_content.append("\n".join(srt_entry))
    
    return "\n\n".join(srt_content)


def convert_json_to_srt_for_llm(json_file_path: str, srt_file_path: str, max_duration_sec: int = 20):
    """
    将阿里云语音转文字的JSON文件转换为针对大模型理解优化的SRT字幕文件
    """
    # 读取JSON文件
    with open(json_file_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    # 生成SRT内容
    srt_content = generate_srt_for_llm(json_data, max_duration_sec * 1000)
    
    # 写入SRT文件
    with open(srt_file_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)


def main():
    # JSON文件路径
    json_file_path = "/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/file/shantou_voice_29.json"
    
    # SRT文件输出路径
    srt_file_path = "/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/file/shantou_voice_29_llm.srt"
    
    # 转换
    convert_json_to_srt_for_llm(json_file_path, srt_file_path, 20)
    
    print(f"已生成针对大模型理解优化的SRT文件: {srt_file_path}")


if __name__ == "__main__":
    main()