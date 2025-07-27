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
                                 output_dir: str, max_workers: int = 4) -> Dict:
    """
    使用多进程提取所有关键帧
    
    Args:
        video_path: 视频文件路径
        subtitle_keyframe_data: 字幕-关键帧匹配数据
        output_dir: 输出目录
        max_workers: 最大工作进程数
        
    Returns:
        Dict: 提取结果统计
    """
    # 创建任务列表
    tasks = []
    
    for i, data_item in enumerate(subtitle_keyframe_data):
        for j, extraction_time in enumerate(data_item['extraction_times']):
            # 计算关键帧文件名
            time_str = extraction_time.replace(':', '').replace('.', '')
            keyframe_filename = f"segment_{i + 1}_keyframe_{time_str}.jpg"
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
                               output_dir: str) -> Dict:
    """
    顺序提取关键帧（用于调试或小规模任务）
    """
    processor = video_processor.VideoProcessor(video_path)
    total_tasks = sum(len(item['extraction_times']) for item in subtitle_keyframe_data)
    successful_count = 0
    failed_count = 0
    
    logger.info(f"准备提取 {total_tasks} 个关键帧（顺序处理）")
    
    try:
        for i, data_item in enumerate(subtitle_keyframe_data):
            for j, extraction_time in enumerate(data_item['extraction_times']):
                # 计算关键帧文件名
                time_str = extraction_time.replace(':', '').replace('.', '')
                keyframe_filename = f"segment_{i + 1}_keyframe_{time_str}.jpg"
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
                args.output_dir
            )
        else:
            logger.info(f"使用多进程处理模式，进程数: {args.max_workers}")
            result = extract_keyframes_multiprocess(
                args.video_path, 
                subtitle_keyframe_data, 
                args.output_dir, 
                args.max_workers
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
