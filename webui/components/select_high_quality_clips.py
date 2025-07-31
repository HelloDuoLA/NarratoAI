#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选择高质量的单人语音片段
根据要求，选择20M以内，15秒到1分钟的单人语音片段
优先选择前后是BGM的片段，这样可以确保是纯人声
"""

import os
import re
import subprocess
from typing import List, Dict
from datetime import datetime


class SubtitleEntry:
    """
    字幕条目类
    """
    def __init__(self, index: int, start_time: str, end_time: str, text: str):
        self.index = index
        self.start_time = start_time
        self.end_time = end_time
        self.text = text
        self.start_ms = self._time_to_milliseconds(start_time)
        self.end_ms = self._time_to_milliseconds(end_time)
        self.duration_ms = self.end_ms - self.start_ms
        self.is_speaker = "[无字幕]" not in text and "[Speaker" in text
        self.is_empty = "[无字幕]" in text
        self.speaker_id = self._extract_speaker_id() if self.is_speaker else None

    def _time_to_milliseconds(self, time_str: str) -> int:
        """
        将时间字符串转换为毫秒
        """
        # 处理格式: HH:MM:SS,mmm
        hours, minutes, seconds = time_str.split(":")
        seconds, milliseconds = seconds.split(",")
        return (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000 + int(milliseconds)

    def _extract_speaker_id(self) -> int:
        """
        提取说话人ID
        """
        match = re.search(r"\[Speaker (\d+)\]", self.text)
        return int(match.group(1)) if match else -1


def parse_srt_file(srt_file_path: str) -> List[SubtitleEntry]:
    """
    解析SRT文件
    
    Args:
        srt_file_path: SRT文件路径
        
    Returns:
        字幕条目列表
    """
    subtitles = []
    
    with open(srt_file_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    
    # 分割字幕块
    blocks = re.split(r'\n\s*\n', content)
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            try:
                # 解析索引
                index = int(lines[0])
                
                # 解析时间轴
                time_line = lines[1]
                start_time, end_time = time_line.split(" --> ")
                
                # 解析文本
                text = "\n".join(lines[2:])
                
                subtitle = SubtitleEntry(index, start_time.strip(), end_time.strip(), text.strip())
                subtitles.append(subtitle)
            except Exception as e:
                print(f"解析字幕块时出错: {e}")
                continue
    
    return subtitles


def find_continuous_speaker_segments(subtitles: List[SubtitleEntry]) -> List[Dict]:
    """
    查找连续的说话人片段
    
    Args:
        subtitles: 字幕条目列表
        
    Returns:
        连续说话人片段列表
    """
    segments = []
    i = 0
    
    while i < len(subtitles):
        # 跳过非说话人片段
        if not subtitles[i].is_speaker:
            i += 1
            continue
            
        # 找到一个说话人片段的开始
        start_idx = i
        end_idx = i
        current_speaker = subtitles[i].speaker_id
        total_duration = subtitles[i].duration_ms
        
        # 向后查找连续的相同说话人片段（中间不能有无字幕）
        j = i + 1
        while j < len(subtitles) and subtitles[j].is_speaker and subtitles[j].speaker_id == current_speaker:
            total_duration += subtitles[j].duration_ms
            end_idx = j
            j += 1
            
        # 创建片段信息
        segment = {
            "start_idx": start_idx,
            "end_idx": end_idx,
            "start_time": subtitles[start_idx].start_time,
            "end_time": subtitles[end_idx].end_time,
            "start_ms": subtitles[start_idx].start_ms,
            "end_time_ms": subtitles[end_idx].end_ms,
            "duration_ms": total_duration,
            "speaker_id": current_speaker,
            "before_is_empty": start_idx > 0 and subtitles[start_idx-1].is_empty,
            "after_is_empty": end_idx < len(subtitles)-1 and subtitles[end_idx+1].is_empty
        }
        
        segments.append(segment)
        i = j if j > i else i + 1
    
    return segments


def find_long_single_segments(subtitles: List[SubtitleEntry], 
                             min_duration_ms: int = 15000) -> List[Dict]:
    """
    查找单行字幕超过最小持续时间的片段
    
    Args:
        subtitles: 字幕条目列表
        min_duration_ms: 最小持续时间（毫秒），默认15秒
        
    Returns:
        长单行字幕片段列表
    """
    long_segments = []
    
    for i, subtitle in enumerate(subtitles):
        # 检查是否为说话人片段且时长超过最小要求
        if subtitle.is_speaker and subtitle.duration_ms >= min_duration_ms:
            # 确保时长不超过1分钟
            if subtitle.duration_ms <= 60000:
                segment = {
                    "start_idx": i,
                    "end_idx": i,
                    "start_time": subtitle.start_time,
                    "end_time": subtitle.end_time,
                    "start_ms": subtitle.start_ms,
                    "end_time_ms": subtitle.end_ms,
                    "duration_ms": subtitle.duration_ms,
                    "speaker_id": subtitle.speaker_id,
                    "before_is_empty": i > 0 and subtitles[i-1].is_empty,
                    "after_is_empty": i < len(subtitles)-1 and subtitles[i+1].is_empty,
                    "is_combined": False
                }
                
                # 计算质量分数
                score = 0
                if segment["before_is_empty"] and segment["after_is_empty"]:
                    score = 3
                elif segment["before_is_empty"] or segment["after_is_empty"]:
                    score = 2
                else:
                    score = 1
                    
                segment["quality_score"] = score
                long_segments.append(segment)
    
    return long_segments


def combine_segments_for_min_duration(subtitles: List[SubtitleEntry], 
                                     min_duration_ms: int = 15000,  # 15秒
                                     max_duration_ms: int = 60000) -> List[Dict]:
    """
    通过拼接片段来满足最小时长要求
    
    Args:
        subtitles: 字幕条目列表
        min_duration_ms: 最小持续时间（毫秒），默认15秒
        max_duration_ms: 最大持续时间（毫秒），默认1分钟
        
    Returns:
        拼接后的片段组合列表
    """
    # 获取所有连续的说话人片段
    continuous_segments = find_continuous_speaker_segments(subtitles)
    
    combined_segments = []
    
    # 尝试拼接同一说话人的不同片段
    speaker_groups = {}
    for segment in continuous_segments:
        speaker_id = segment["speaker_id"]
        if speaker_id not in speaker_groups:
            speaker_groups[speaker_id] = []
        speaker_groups[speaker_id].append(segment)
    
    # 对每个说话人，尝试拼接相邻的片段（仅相邻片段）
    for speaker_id, segments in speaker_groups.items():
        if len(segments) < 2:
            continue
            
        # 尝试拼接相邻片段
        i = 0
        while i < len(segments):
            current_segment = segments[i]
            total_duration = current_segment["duration_ms"]
            combined_indices = [i]
            
            # 检查下一个片段是否相邻
            j = i + 1
            while j < len(segments):
                # 检查是否相邻（下一个片段的开始索引应该等于当前片段的结束索引+1）
                if segments[j]["start_idx"] == segments[combined_indices[-1]]["end_idx"] + 1:
                    # 检查添加这个片段是否会超过1分钟
                    if total_duration + segments[j]["duration_ms"] <= max_duration_ms:
                        total_duration += segments[j]["duration_ms"]
                        combined_indices.append(j)
                        j += 1
                    else:
                        break
                else:
                    # 不相邻，停止拼接
                    break
            
            # 如果组合满足时长要求（15秒到1分钟）且包含多个片段
            if len(combined_indices) > 1 and total_duration >= min_duration_ms:
                # 创建组合片段
                first_segment = segments[combined_indices[0]]
                last_segment = segments[combined_indices[-1]]
                
                combined_segment = {
                    "segments": [segments[idx] for idx in combined_indices],
                    "start_time": first_segment["start_time"],
                    "end_time": last_segment["end_time"],
                    "start_ms": first_segment["start_ms"],
                    "end_time_ms": last_segment["end_time_ms"],
                    "duration_ms": total_duration,
                    "speaker_id": speaker_id,
                    "is_combined": True,
                    "segment_count": len(combined_indices)
                }
                
                # 检查组合片段前后是否是BGM
                combined_segment["before_is_empty"] = first_segment["before_is_empty"]
                combined_segment["after_is_empty"] = last_segment["after_is_empty"]
                
                # 计算质量分数（拼接片段的质量分数会降低）
                base_score = 0
                if combined_segment["before_is_empty"] and combined_segment["after_is_empty"]:
                    base_score = 3
                elif combined_segment["before_is_empty"] or combined_segment["after_is_empty"]:
                    base_score = 2
                else:
                    base_score = 1
                
                # 拼接片段的质量分数降低一级
                # 3 -> 2, 2 -> 1, 1 -> 1
                combined_segment["quality_score"] = max(1, base_score - 1)
                    
                combined_segments.append(combined_segment)
            
            i += 1 if len(combined_indices) == 1 else len(combined_indices)
    
    return combined_segments


def find_speaker_representatives(subtitles: List[SubtitleEntry], 
                                long_single_clips: List[Dict],
                                combined_clips: List[Dict]) -> List[Dict]:
    """
    确保每个说话人都有代表片段
    对于没有单行片段超过15秒的说话人，尝试通过拼接为其提供片段
    
    Args:
        subtitles: 字幕条目列表
        long_single_clips: 单行字幕超过15秒的片段列表
        combined_clips: 拼接片段列表
        
    Returns:
        每个说话人的代表片段列表
    """
    # 获取所有说话人ID
    speaker_ids = set()
    for subtitle in subtitles:
        if subtitle.is_speaker:
            speaker_ids.add(subtitle.speaker_id)
    
    # 已经有代表片段的说话人
    represented_speakers = set()
    for clip in long_single_clips:
        represented_speakers.add(clip["speaker_id"])
    
    # 为没有代表片段的说话人添加拼接片段
    representative_clips = long_single_clips.copy()
    
    # 按说话人分组拼接片段
    combined_by_speaker = {}
    for clip in combined_clips:
        speaker_id = clip["speaker_id"]
        if speaker_id not in combined_by_speaker:
            combined_by_speaker[speaker_id] = []
        combined_by_speaker[speaker_id].append(clip)
    
    # 为没有代表的说话人添加最佳拼接片段
    for speaker_id in speaker_ids:
        if speaker_id not in represented_speakers and speaker_id in combined_by_speaker:
            # 选择质量最好的拼接片段
            best_combined = max(combined_by_speaker[speaker_id], 
                              key=lambda x: (x["quality_score"], x["duration_ms"]))
            representative_clips.append(best_combined)
    
    return representative_clips


def extract_audio_clip(video_path: str, output_path: str, start_time: str, end_time: str) -> bool:
    """
    使用FFmpeg提取音频片段
    
    Args:
        video_path: 视频文件路径
        output_path: 输出音频文件路径
        start_time: 开始时间 (HH:MM:SS,mmm)
        end_time: 结束时间 (HH:MM:SS,mmm)
        
    Returns:
        是否成功提取
    """
    # 转换时间格式，将逗号替换为点
    start_time_ffmpeg = start_time.replace(',', '.')
    end_time_ffmpeg = end_time.replace(',', '.')
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-ss", start_time_ffmpeg,
        "-to", end_time_ffmpeg,
        "-vn",  # 禁用视频
        "-acodec", "pcm_s16le",  # 使用无损音频编解码器
        "-ar", "44100",  # 采样率
        "-ac", "2",  # 双声道
        output_path
    ]
    
    try:
        # 执行FFmpeg命令并捕获输出
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and os.path.exists(output_path):
            return True
        else:
            print(f"  FFmpeg错误输出: {result.stderr}")
            return False
    except Exception as e:
        print(f"  执行FFmpeg时发生异常: {e}")
        return False


def check_file_size(file_path: str, max_size_mb: int) -> bool:
    """
    检查文件大小是否符合要求
    
    Args:
        file_path: 文件路径
        max_size_mb: 最大大小（MB）
        
    Returns:
        是否符合大小要求
    """
    if not os.path.exists(file_path):
        return False
        
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    return file_size_mb <= max_size_mb


def check_ffmpeg():
    """
    检查FFmpeg是否已安装
    """
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False


def select_high_quality_clips(srt_file_path: str, video_file_path: str, output_dir: str) -> List[str]:
    """
    选择高质量的音频片段
    
    Args:
        srt_file_path: SRT字幕文件路径
        video_file_path: 音频/视频文件路径
        output_dir: 输出目录路径
        
    Returns:
        提取的音频文件完整路径列表
    """
    # 检查FFmpeg是否已安装
    if not check_ffmpeg():
        raise RuntimeError("错误: 未找到FFmpeg，请先安装FFmpeg")
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 检查文件是否存在
    if not os.path.exists(srt_file_path):
        raise FileNotFoundError(f"错误: SRT文件不存在: {srt_file_path}")
    
    # 检查视频文件路径是否正确
    if not os.path.exists(video_file_path):
        raise FileNotFoundError(f"错误: 音频文件不存在: {video_file_path}")
    
    # 解析SRT文件
    subtitles = parse_srt_file(srt_file_path)
    
    # 首先查找单行字幕超过15秒的片段
    long_single_clips = find_long_single_segments(subtitles, min_duration_ms=15000)
    
    # 查找通过拼接获得的片段
    combined_clips = combine_segments_for_min_duration(subtitles, min_duration_ms=15000, max_duration_ms=60000)
    
    # 确保每个说话人都有代表片段
    speaker_representatives = find_speaker_representatives(subtitles, long_single_clips, combined_clips)
    
    # 合并所有片段，按新优先级排序：
    # 1. 单行长片段 > 拼接片段
    # 2. 前后都是BGM(质量分3) > 单一BGM(质量分2) > 无BGM(质量分1)
    # 3. 时长较长的优先
    all_clips = long_single_clips + combined_clips
    
    # 按照新的优先级规则排序：
    # 1. 首先按是否为拼接片段排序（单行片段优先）
    # 2. 然后按质量分数排序（前后BGM > 单一BGM > 无BGM）
    # 3. 最后按时长排序
    all_clips.sort(key=lambda x: (x.get("is_combined", False), -x["quality_score"], -x["duration_ms"]))
    
    # 去重（避免同一个片段被多次包含）
    unique_clips = []
    seen_ranges = set()
    
    for clip in all_clips:
        range_key = (clip["start_ms"], clip["end_time_ms"])
        if range_key not in seen_ranges:
            unique_clips.append(clip)
            seen_ranges.add(range_key)
    
    # 确保每个说话人都有代表，将代表片段移到前面
    speaker_clips = []
    other_clips = []
    speaker_represented = set()
    
    # 首先添加每个说话人的代表片段
    for clip in unique_clips:
        if clip["speaker_id"] not in speaker_represented:
            speaker_clips.append(clip)
            speaker_represented.add(clip["speaker_id"])
        else:
            other_clips.append(clip)
    
    # 重新排序，优先确保说话人代表性
    unique_clips = speaker_clips + other_clips
    
    # 提取前几个质量最高的片段
    extracted_count = 0
    max_clips = 15  # 最多提取15个片段
    extracted_file_paths = []  # 记录提取的文件完整路径
    
    for i, clip in enumerate(unique_clips):
        if extracted_count >= max_clips:
            break
            
        # 生成输出文件名，使用实际的说话人标识
        if clip.get("is_combined", False):
            output_filename = f"speaker{clip['speaker_id']}_combined_clip_{extracted_count+1}_score{clip['quality_score']}_duration{clip['duration_ms']//1000}s.wav"
        else:
            output_filename = f"speaker{clip['speaker_id']}_single_clip_{extracted_count+1}_score{clip['quality_score']}_duration{clip['duration_ms']//1000}s.wav"
            
        output_path = os.path.join(output_dir, output_filename)
        
        # 提取音频片段
        success = extract_audio_clip(video_file_path, output_path, clip['start_time'], clip['end_time'])
        if success:
            # 检查文件大小
            if check_file_size(output_path, 20):
                extracted_count += 1
                extracted_file_paths.append(output_path)  # 记录成功提取的文件完整路径
            else:
                os.remove(output_path)
    
    return extracted_file_paths


def main():
    """
    主函数
    """
    # 检查FFmpeg是否已安装
    if not check_ffmpeg():
        print("错误: 未找到FFmpeg，请先安装FFmpeg")
        return
    
    # 创建以当前时间戳命名的输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/audio/{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    
    # SRT文件路径（用户提供的正确路径）
    srt_file_path = "/disk/disk1/xzc_data/Competition/baidu_lic/3rdProject/funasr/file/shantou_voice_31_llm.srt"
    
    # 音频文件路径（用户提供的正确路径）
    video_file_path = "/disk/disk1/xzc_data/Competition/baidu_lic/data/output/music/shantou/shantou_vocals.wav"
    
    try:
        # 调用函数提取高质量片段
        extracted_files = select_high_quality_clips(srt_file_path, video_file_path, output_dir)
        
        print(f"完成! 共提取 {len(extracted_files)} 个音频片段到目录: {output_dir}")
        
        # 打印所有已提取的文件名
        if extracted_files:
            print("\n已提取的文件列表:")
            for file_path in extracted_files:
                print(f"  {file_path}")
    except Exception as e:
        print(f"处理过程中出现错误: {e}")


if __name__ == "__main__":
    main()