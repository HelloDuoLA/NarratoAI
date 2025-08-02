#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阿里云语音识别结果转SRT字幕格式，短字幕
修正版：确保标点符号显示与否不影响分割逻辑
"""

import json
import re
import os
from typing import List, Dict, Tuple


def split_text_by_punctuation(text: str) -> List[str]:
    """
    根据标点符号将文本切分为句子，保留标点符号
    """
    # 使用正则表达式按照标点符号切分句子，保留标点符号
    parts = re.split(r'([，。！？；])', text)
    sentences = []
    
    # 组合文本和标点符号
    i = 0
    while i < len(parts):
        if i + 1 < len(parts) and re.match(r'[，。！？；]', parts[i + 1]):
            # 文本后跟标点符号
            sentences.append(parts[i] + parts[i + 1])
            i += 2
        else:
            # 只有文本或只有标点符号
            if parts[i].strip():  # 忽略空字符串
                sentences.append(parts[i])
            i += 1
    
    return sentences


def wrap_text(text: str, max_chars_per_line: int, show_punctuation: bool = True) -> List[str]:
    """
    将文本按照指定字符数换行，标点符号处理
    """
    lines = []
    
    # 如果不显示标点符号，则移除标点符号（仅在输出时移除，不影响换行计算）
    process_text = text
    if not show_punctuation:
        # 移除常见中文标点符号（仅在最终输出时）
        punctuation = '，。！？；：""''（）【】《》、'
        # 但我们仍然需要在计算行数时考虑它们，所以这里不移除
    
    # 计算需要的行数
    total_chars = len(text)
    if total_chars <= max_chars_per_line:
        # 如果显示标点符号则直接输出，否则移除标点符号
        if not show_punctuation:
            # 移除常见中文标点符号
            punctuation = '，。！？；：""''（）【】《》、'
            output_text = text
            for p in punctuation:
                output_text = output_text.replace(p, '')
            lines.append(output_text)
        else:
            lines.append(text)
    else:
        # 当文本超过最大字符数时，我们将其分成多个字幕条目（另起一条）
        start = 0
        while start < len(text):
            end = min(start + max_chars_per_line, len(text))
            line_text = text[start:end]
            
            # 根据设置决定是否显示标点符号
            if not show_punctuation:
                # 移除常见中文标点符号
                punctuation = '，。！？；：""''（）【】《》、'
                for p in punctuation:
                    line_text = line_text.replace(p, '')
            
            if line_text.strip():  # 只添加非空行
                lines.append(line_text)
            start = end
    
    return lines


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


def generate_srt(json_data: Dict, 
                 max_chars_per_line: int = 20, 
                 show_speaker: bool = True, 
                 show_punctuation: bool = True) -> str:
    """
    根据阿里云语音转文字的JSON数据生成SRT字幕内容
    
    Args:
        json_data: 阿里云语音转文字的JSON数据
        max_chars_per_line: 每行最大字符数
        show_speaker: 是否显示说话人标识
        show_punctuation: 是否显示标点符号
    """
    srt_content = []
    subtitle_index = 1
    
    # 遍历所有句子
    for transcript in json_data.get("transcripts", []):
        for sentence in transcript.get("sentences", []):
            begin_time = sentence.get("begin_time", 0)
            end_time = sentence.get("end_time", 0)
            speaker_id = sentence.get("speaker_id", 0)
            text = sentence.get("text", "")
            
            # 按标点符号切分句子
            sub_sentences = split_text_by_punctuation(text)
            
            # 计算每个子句子的时间间隔
            if len(sub_sentences) > 1:
                time_per_subsentence = (end_time - begin_time) // len(sub_sentences)
            else:
                time_per_subsentence = end_time - begin_time
            
            for i, sub_sentence in enumerate(sub_sentences):
                if not sub_sentence.strip():
                    continue
                
                # 计算子句子的时间范围
                sub_begin_time = begin_time + i * time_per_subsentence
                sub_end_time = begin_time + (i + 1) * time_per_subsentence
                if i == len(sub_sentences) - 1:  # 最后一个子句子确保结束时间正确
                    sub_end_time = end_time
                
                # 处理超长字幕 - 另起一条而不是分两行
                # 先检查是否需要另起一条
                if len(sub_sentence) <= max_chars_per_line:
                    # 不需要另起一条
                    lines = []
                    # 根据设置决定是否显示标点符号
                    process_text = sub_sentence
                    if not show_punctuation:
                        # 移除常见中文标点符号
                        punctuation = '，。！？；：""''（）【】《》、'
                        for p in punctuation:
                            process_text = process_text.replace(p, '')
                    
                    if process_text.strip():
                        lines.append(process_text)
                    
                    # 构造SRT条目
                    if lines:  # 确保有实际内容
                        srt_entry = []
                        srt_entry.append(str(subtitle_index))
                        srt_entry.append(f"{milliseconds_to_srt_time(sub_begin_time)} --> {milliseconds_to_srt_time(sub_end_time)}")
                        
                        # 添加说话人标识（如果需要）
                        prefix = ""
                        if show_speaker:
                            prefix = f"[Speaker {speaker_id}]: "
                        
                        # 添加文本行
                        for line in lines:
                            if line.strip():
                                srt_entry.append(prefix + line)
                                # 只在第一行添加说话人标识
                                prefix = ""
                        
                        srt_content.append("\n".join(srt_entry))
                        subtitle_index += 1
                else:
                    # 需要另起一条字幕，并且要均匀分配文字
                    # 计算需要多少个条目
                    total_chars = len(sub_sentence)
                    num_entries = (total_chars + max_chars_per_line - 1) // max_chars_per_line
                    
                    # 计算每个条目应该包含的字符数，使分配更均匀
                    chars_per_entry = total_chars // num_entries
                    remaining_chars = total_chars % num_entries
                    
                    # 计算每个条目的时间范围
                    time_per_entry = (sub_end_time - sub_begin_time) / num_entries
                    
                    start = 0
                    entry_index = 0
                    while start < len(sub_sentence):
                        # 为了均匀分配，前remaining_chars个条目每个加1个字符
                        entry_length = chars_per_entry + (1 if entry_index < remaining_chars else 0)
                        end = min(start + entry_length, len(sub_sentence))
                        entry_text = sub_sentence[start:end]
                        
                        # 根据设置决定是否显示标点符号
                        if not show_punctuation:
                            # 移除常见中文标点符号
                            punctuation = '，。！？；：""''（）【】《》、'
                            for p in punctuation:
                                entry_text = entry_text.replace(p, '')
                        
                        if entry_text.strip():
                            # 计算时间范围
                            entry_begin_time = int(sub_begin_time + entry_index * time_per_entry)
                            entry_end_time = int(sub_begin_time + (entry_index + 1) * time_per_entry)
                            if entry_index == num_entries - 1:  # 最后一个确保结束时间正确
                                entry_end_time = sub_end_time
                            
                            srt_entry = []
                            srt_entry.append(str(subtitle_index))
                            srt_entry.append(f"{milliseconds_to_srt_time(entry_begin_time)} --> {milliseconds_to_srt_time(entry_end_time)}")
                            
                            # 添加说话人标识（如果需要）
                            prefix = ""
                            if show_speaker:
                                prefix = f"[Speaker {speaker_id}]: "
                            
                            srt_entry.append(prefix + entry_text)
                            srt_content.append("\n".join(srt_entry))
                            subtitle_index += 1
                            entry_index += 1
                        
                        start = end
    
    return "\n\n".join(srt_content)


def convert_json_to_srt(json_file_path: str, 
                        srt_file_path: str,
                        max_chars_per_line: int = 20,
                        show_speaker: bool = False,
                        show_punctuation: bool = False):
    """
    将阿里云语音转文字的JSON文件转换为SRT字幕文件
    """
    # 读取JSON文件
    with open(json_file_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    # 生成SRT内容
    srt_content = generate_srt(
        json_data=json_data,
        max_chars_per_line=max_chars_per_line,
        show_speaker=show_speaker,
        show_punctuation=show_punctuation
    )
    
    # 写入SRT文件
    with open(srt_file_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)


def main():
    # JSON文件路径
    json_file_path = "/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/file/一條麻甩在汕頭.json"
    
    # 获取JSON文件的基本名称（不含扩展名）
    base_name = os.path.splitext(os.path.basename(json_file_path))[0]
    base_dir = os.path.dirname(json_file_path)
    
    # 1. 有说话人有标点
    srt_file_1 = os.path.join("/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/file", f"{base_name}_with_speaker_punct.srt")
    convert_json_to_srt(json_file_path, srt_file_1, 20, True, True)
    print(f"已生成SRT文件（有说话人有标点）: {srt_file_1}")
    
    # 2. 无说话人无标点
    srt_file_2 = os.path.join("/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/file", f"{base_name}_no_speaker_no_punct.srt")
    convert_json_to_srt(json_file_path, srt_file_2, 20, False, False)
    print(f"已生成SRT文件（无说话人无标点）: {srt_file_2}")
    
    # 3. 无说话人有标点
    srt_file_3 = os.path.join("/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/file", f"{base_name}_no_speaker_with_punct.srt")
    convert_json_to_srt(json_file_path, srt_file_3, 20, False, True)
    print(f"已生成SRT文件（无说话人有标点）: {srt_file_3}")
    
    # 4. 有说话人无标点
    srt_file_4 = os.path.join("/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/file", f"{base_name}_with_speaker_no_punct.srt")
    convert_json_to_srt(json_file_path, srt_file_4, 20, True, False)
    print(f"已生成SRT文件（有说话人无标点）: {srt_file_4}")


if __name__ == "__main__":
    main()
