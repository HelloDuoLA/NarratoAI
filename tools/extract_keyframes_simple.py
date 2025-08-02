#!/usr/bin/env python3
"""
简化的独立关键帧提取工具

这个工具用于从视频中提取关键帧，支持多进程处理。
通过命令行调用，避免在Streamlit中使用多进程导致的界面刷新问题。

监控方式: 直接通过文件数量统计进度，无需复杂的JSON进度文件
"""

import os
import sys
import json
import argparse
import multiprocessing as mp
from pathlib import Path
from typing import List, Dict
from loguru import logger

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.utils import utils, video_processor


def calculate_extraction_times_with_sampling(start_seconds: float, end_seconds: float, 
                                            interval_seconds: float = None, 
                                            max_frames: int = -1) -> List[str]:
    """
    根据间隔和最大帧数计算提取时间点
    
    Args:
        start_seconds: 开始时间（秒）
        end_seconds: 结束时间（秒）
        interval_seconds: 间隔秒数，如果为None则只提取中间帧
        max_frames: 最大帧数，-1表示不限制
        
    Returns:
        List[str]: 时间点列表，格式如 "00:01:30.500"
    """
    duration = end_seconds - start_seconds
    
    if interval_seconds is None:
        # 默认行为：只提取中间一帧
        mid_time = start_seconds + duration / 2
        return [utils.seconds_to_time(mid_time)]
    
    # 按间隔计算时间点
    time_points = []
    current_time = start_seconds
    
    while current_time <= end_seconds:
        time_points.append(current_time)
        current_time += interval_seconds
    
    # 如果没有时间点或最后一个时间点太接近结束时间，确保至少有一帧
    if not time_points:
        time_points = [start_seconds + duration / 2]
    elif len(time_points) == 1 and time_points[0] > end_seconds - 0.1:
        time_points = [start_seconds + duration / 2]
    
    # 应用最大帧数限制
    if max_frames > 0 and len(time_points) > max_frames:
        # 均匀采样到最大帧数
        indices = [int(i * (len(time_points) - 1) / (max_frames - 1)) for i in range(max_frames)]
        time_points = [time_points[i] for i in indices]
    
    # 转换为时间字符串格式
    return [utils.seconds_to_time(t) for t in time_points]


def extract_single_keyframe_worker(task_data: Dict) -> bool:
    """
    多进程工作函数：提取单个关键帧
    
    Args:
        task_data: 任务数据
            - video_path: 视频路径
            - time_seconds: 时间点（秒）
            - output_path: 输出路径
    
    Returns:
        bool: 是否成功
    """
    try:
        video_path = task_data['video_path']
        time_seconds = task_data['time_seconds']
        output_path = task_data['output_path']
        
        # 在工作进程中重新初始化视频处理器
        processor = video_processor.VideoProcessor(video_path)
        
        # 使用超级兼容性方案提取单帧
        success = processor._extract_frame_ultra_compatible(
            timestamp=time_seconds,
            output_path=output_path
        )
        
        if success:
            logger.debug(f"成功提取关键帧: {os.path.basename(output_path)}")
        else:
            logger.warning(f"关键帧提取失败: {os.path.basename(output_path)}")
            
        return success
        
    except Exception as e:
        logger.error(f"提取关键帧时发生异常: {e}")
        return False


def extract_keyframes_multiprocess(video_path: str, subtitle_keyframe_data: List[Dict], 
                                 output_dir: str, max_workers: int = 4,
                                 interval_seconds: float = None, max_frames: int = -1) -> Dict:
    """
    使用多进程提取所有关键帧
    
    Args:
        video_path: 视频文件路径
        subtitle_keyframe_data: 字幕-关键帧匹配数据
        output_dir: 输出目录
        max_workers: 最大工作进程数
        interval_seconds: 间隔秒数
        max_frames: 每个片段最大帧数
        
    Returns:
        Dict: 提取结果统计
    """
    # 创建任务列表
    tasks = []
    
    for i, data_item in enumerate(subtitle_keyframe_data):
        # 重新计算提取时间点（如果需要）
        if interval_seconds is not None or max_frames != -1:
            # 从时间戳中解析开始和结束时间
            timestamp = data_item.get('timestamp', '00:00:00,000 --> 00:00:01,000')
            duration = data_item.get('duration', 1.0)
            
            if ' --> ' in timestamp:
                start_time_str, end_time_str = timestamp.split(' --> ')
                start_seconds = utils.time_to_seconds(start_time_str.replace('.', ','))
                end_seconds = utils.time_to_seconds(end_time_str.replace('.', ','))
            else:
                # 如果没有时间戳信息，使用duration
                start_seconds = i * duration  # 假设连续的片段
                end_seconds = start_seconds + duration
            
            # 使用新的采样策略
            extraction_times = calculate_extraction_times_with_sampling(
                start_seconds, end_seconds, interval_seconds, max_frames
            )
        else:
            # 使用原始数据
            extraction_times = data_item['extraction_times']
        
        for j, extraction_time in enumerate(extraction_times):
            # 计算关键帧文件名
            time_str = extraction_time.replace(':', '').replace('.', '')
            keyframe_filename = f"segment_{i + 1}_keyframe_{j+1}_{time_str}.jpg"
            keyframe_path = os.path.join(output_dir, keyframe_filename)
            
            # 将时间字符串转换为秒数
            time_seconds = utils.time_to_seconds(extraction_time.replace('.', ','))
            
            task_data = {
                'video_path': video_path,
                'time_seconds': time_seconds,
                'output_path': keyframe_path
            }
            
            tasks.append(task_data)
    
    total_tasks = len(tasks)
    logger.info(f"准备提取 {total_tasks} 个关键帧，使用 {max_workers} 个进程")
    
    if interval_seconds is not None:
        logger.info(f"采样间隔: {interval_seconds}秒")
    if max_frames > 0:
        logger.info(f"每片段最大帧数: {max_frames}")
    
    # 使用多进程池处理任务
    successful_count = 0
    failed_count = 0
    
    try:
        with mp.Pool(processes=max_workers) as pool:
            # 提交所有任务
            results = pool.map(extract_single_keyframe_worker, tasks)
            
            # 统计结果
            successful_count = sum(1 for result in results if result)
            failed_count = total_tasks - successful_count
    
    except Exception as e:
        logger.error(f"多进程处理失败: {e}")
        raise
    
    logger.info(f"关键帧提取完成，成功: {successful_count}/{total_tasks}, 失败: {failed_count}")
    
    return {
        'total_expected': total_tasks,
        'successful_extractions': successful_count,
        'failed_extractions': failed_count
    }


def extract_keyframes_sequential(video_path: str, subtitle_keyframe_data: List[Dict], 
                               output_dir: str, interval_seconds: float = None, 
                               max_frames: int = -1) -> Dict:
    """
    顺序提取关键帧（用于调试或小规模任务）
    """
    processor = video_processor.VideoProcessor(video_path)
    
    # 计算总任务数
    total_tasks = 0
    for data_item in subtitle_keyframe_data:
        if interval_seconds is not None or max_frames != -1:
            # 从时间戳中解析开始和结束时间
            timestamp = data_item.get('timestamp', '00:00:00,000 --> 00:00:01,000')
            duration = data_item.get('duration', 1.0)
            
            if ' --> ' in timestamp:
                start_time_str, end_time_str = timestamp.split(' --> ')
                start_seconds = utils.time_to_seconds(start_time_str.replace('.', ','))
                end_seconds = utils.time_to_seconds(end_time_str.replace('.', ','))
            else:
                # 如果没有时间戳信息，使用duration
                start_seconds = 0
                end_seconds = duration
            
            extraction_times = calculate_extraction_times_with_sampling(
                start_seconds, end_seconds, interval_seconds, max_frames
            )
            total_tasks += len(extraction_times)
        else:
            total_tasks += len(data_item['extraction_times'])
    
    successful_count = 0
    failed_count = 0
    
    logger.info(f"准备提取 {total_tasks} 个关键帧（顺序处理）")
    
    if interval_seconds is not None:
        logger.info(f"采样间隔: {interval_seconds}秒")
    if max_frames > 0:
        logger.info(f"每片段最大帧数: {max_frames}")
    
    try:
        for i, data_item in enumerate(subtitle_keyframe_data):
            # 重新计算提取时间点（如果需要）
            if interval_seconds is not None or max_frames != -1:
                # 从时间戳中解析开始和结束时间
                timestamp = data_item.get('timestamp', '00:00:00,000 --> 00:00:01,000')
                duration = data_item.get('duration', 1.0)
                
                if ' --> ' in timestamp:
                    start_time_str, end_time_str = timestamp.split(' --> ')
                    start_seconds = utils.time_to_seconds(start_time_str.replace('.', ','))
                    end_seconds = utils.time_to_seconds(end_time_str.replace('.', ','))
                else:
                    # 如果没有时间戳信息，使用duration
                    start_seconds = i * duration  # 假设连续的片段
                    end_seconds = start_seconds + duration
                
                extraction_times = calculate_extraction_times_with_sampling(
                    start_seconds, end_seconds, interval_seconds, max_frames
                )
            else:
                extraction_times = data_item['extraction_times']
            
            for j, extraction_time in enumerate(extraction_times):
                # 计算关键帧文件名
                time_str = extraction_time.replace(':', '').replace('.', '')
                keyframe_filename = f"segment_{i + 1}_keyframe_{j+1}_{time_str}.jpg"
                keyframe_path = os.path.join(output_dir, keyframe_filename)
                
                # 将时间字符串转换为秒数
                time_seconds = utils.time_to_seconds(extraction_time.replace('.', ','))
                
                # 使用超级兼容性方案提取单帧
                success = processor._extract_frame_ultra_compatible(
                    timestamp=time_seconds,
                    output_path=keyframe_path
                )
                
                if success:
                    successful_count += 1
                    logger.debug(f"成功提取关键帧 {i+1}-{j+1}: {keyframe_filename}")
                else:
                    failed_count += 1
                    logger.warning(f"第{i+1}个字幕的第{j+1}个关键帧提取失败: {keyframe_filename}")
    
    except Exception as e:
        logger.error(f"顺序提取关键帧失败: {e}")
        raise
    
    logger.info(f"关键帧提取完成，成功: {successful_count}/{total_tasks}, 失败: {failed_count}")
    
    return {
        'total_expected': total_tasks,
        'successful_extractions': successful_count,
        'failed_extractions': failed_count
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='简化的独立关键帧提取工具')
    parser.add_argument('--video_path', required=True, help='视频文件路径')
    parser.add_argument('--subtitle_keyframe_match', required=True, help='字幕-关键帧匹配数据JSON文件路径')
    parser.add_argument('--output_dir', required=True, help='输出目录')
    parser.add_argument('--max_workers', type=int, default=4, help='最大工作进程数')
    parser.add_argument('--sequential', action='store_true', help='使用顺序处理而不是多进程')
    parser.add_argument('--log_level', default='INFO', help='日志级别')
    
    # 新增参数
    parser.add_argument('--interval_seconds', type=float, default=None, 
                       help='间隔多少秒提取一帧，如果不指定则只提取中间帧')
    parser.add_argument('--max_frames', type=int, default=-1, 
                       help='每个片段最多提取多少帧，-1表示不限制。如果间隔采样超过此数量，会均匀采样到指定帧数')
    
    args = parser.parse_args()
    
    # 配置日志
    logger.remove()
    logger.add(
        sys.stderr,
        level=args.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # 验证输入参数
    if not os.path.exists(args.video_path):
        logger.error(f"视频文件不存在: {args.video_path}")
        sys.exit(1)
    
    if not os.path.exists(args.subtitle_keyframe_match):
        logger.error(f"字幕匹配文件不存在: {args.subtitle_keyframe_match}")
        sys.exit(1)
    
    # 参数验证
    if args.interval_seconds is not None and args.interval_seconds <= 0:
        logger.error("间隔秒数必须大于0")
        sys.exit(1)
    
    if args.max_frames < -1 or args.max_frames == 0:
        logger.error("最大帧数必须为-1（不限制）或大于0的整数")
        sys.exit(1)
    
    # 确保输出目录存在
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 读取字幕-关键帧匹配数据
    try:
        with open(args.subtitle_keyframe_match, 'r', encoding='utf-8') as f:
            subtitle_keyframe_data = json.load(f)
        logger.info(f"加载字幕匹配数据，共 {len(subtitle_keyframe_data)} 个片段")
    except Exception as e:
        logger.error(f"读取字幕匹配文件失败: {e}")
        sys.exit(1)
    
    # 执行关键帧提取
    try:
        if args.sequential:
            logger.info("使用顺序处理模式")
            result = extract_keyframes_sequential(
                args.video_path, 
                subtitle_keyframe_data, 
                args.output_dir,
                args.interval_seconds,
                args.max_frames
            )
        else:
            logger.info(f"使用多进程处理模式，进程数: {args.max_workers}")
            result = extract_keyframes_multiprocess(
                args.video_path, 
                subtitle_keyframe_data, 
                args.output_dir, 
                args.max_workers,
                args.interval_seconds,
                args.max_frames
            )
        
        logger.info(f"关键帧提取完成")
        logger.info(f"成功: {result['successful_extractions']}/{result['total_expected']}")
        logger.info(f"失败: {result['failed_extractions']}")
        
        # 返回相应的退出码
        if result['successful_extractions'] == 0:
            logger.error("没有成功提取任何关键帧")
            sys.exit(1)
        elif result['failed_extractions'] > 0:
            logger.warning(f"部分关键帧提取失败")
            sys.exit(2)  # 部分成功
        else:
            logger.info("所有关键帧提取成功")
            sys.exit(0)  # 完全成功
        
    except Exception as e:
        logger.error(f"关键帧提取失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
