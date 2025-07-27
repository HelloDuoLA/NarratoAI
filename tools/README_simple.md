# 简化的关键帧提取方案

## 概述

这是一个重新设计的关键帧提取方案，解决了以下问题：

1. **简化监听方式**：直接统计文件数量，不再依赖复杂的JSON进度文件
2. **预先确定文件名**：在开始提取之前就确定所有关键帧的文件路径
3. **移除不必要的文件读写**：不需要读取更新后的匹配数据
4. **提高可靠性**：减少文件操作，降低出错概率

## 核心改进

### 1. 预先生成文件路径

```python
# 在提取之前就确定所有文件路径
for i, data_item in enumerate(subtitle_keyframe_data):
    for j, extraction_time in enumerate(data_item['extraction_times']):
        time_str = extraction_time.replace(':', '').replace('.', '')
        keyframe_filename = f"segment_{i + 1}_keyframe_{time_str}.jpg"
        keyframe_path = os.path.join(video_keyframes_dir, keyframe_filename)
        
        # 预先将路径添加到数据结构中
        data_item['keyframe_paths'].append(keyframe_path)
```

### 2. 简化的进度监听

```python
# 直接统计文件数量，无需JSON进度文件
while True:
    if os.path.exists(video_keyframes_dir):
        all_files = os.listdir(video_keyframes_dir)
        keyframe_files = [
            f for f in all_files 
            if f.endswith('.jpg') and 'segment_' in f and 'keyframe_' in f
        ]
        current_count = len(keyframe_files)
        
        if current_count != last_count:
            progress_percent = 17 + (current_count / total_expected) * 3
            update_progress(progress_percent, f"已提取 {current_count}/{total_expected} 个关键帧")
            last_count = current_count
```

### 3. 结果验证

```python
# 检查预定义路径中哪些文件实际存在
for data_item in subtitle_keyframe_data:
    existing_paths = []
    for keyframe_path in data_item['keyframe_paths']:
        if os.path.exists(keyframe_path):
            existing_paths.append(keyframe_path)
            successful_extractions += 1
        else:
            failed_extractions += 1
    
    # 更新为实际存在的文件路径
    data_item['keyframe_paths'] = existing_paths
```

## 文件结构

```
tools/
├── extract_keyframes_simple.py    # 简化的独立提取工具
├── test_extract_keyframes_simple.py # 测试脚本
└── README_simple.md              # 本文档
```

## 使用方法

### 1. 独立工具使用

```bash
# 基本用法
python tools/extract_keyframes_simple.py \
    --video_path /path/to/video.mp4 \
    --subtitle_keyframe_match /path/to/match.json \
    --output_dir /path/to/output \
    --max_workers 4

# 顺序处理（调试用）
python tools/extract_keyframes_simple.py \
    --video_path /path/to/video.mp4 \
    --subtitle_keyframe_match /path/to/match.json \
    --output_dir /path/to/output \
    --sequential \
    --log_level DEBUG
```

### 2. 主程序集成

主程序已经自动使用简化的方案：

1. 预先生成所有文件路径
2. 启动独立提取工具
3. 监听文件数量变化
4. 验证最终结果

## 优势

### 1. 简化性
- 无需复杂的JSON进度文件
- 直接的文件数量统计
- 更少的文件操作

### 2. 可靠性
- 预先确定的文件路径
- 减少文件读写错误
- 更好的错误处理

### 3. 性能
- 更快的进度检查
- 减少磁盘I/O
- 更高效的监控

### 4. 可维护性
- 更清晰的代码逻辑
- 更容易调试
- 更简单的错误排查

## 文件命名规则

关键帧文件命名遵循以下规则：

```
segment_{段落索引}_keyframe_{时间戳}.jpg
```

示例：
- `segment_1_keyframe_000130500.jpg` （对应 00:01:30.500）
- `segment_2_keyframe_000245123.jpg` （对应 00:02:45.123）
- `segment_3_keyframe_010000000.jpg` （对应 01:00:00.000）

时间戳转换规则：
- 移除冒号和点号
- 保持 HHMMSSMMM 格式（时时分分秒秒毫毫毫）

## 错误处理

### 1. 预检查
- 验证视频文件存在
- 验证字幕匹配文件格式
- 检查输出目录权限

### 2. 运行时监控
- 进程超时检测
- 文件生成监控
- 异常情况处理

### 3. 结果验证
- 文件存在性检查
- 成功/失败统计
- 清理失败的文件

## 返回值

独立工具的退出码：
- `0`: 所有关键帧提取成功
- `1`: 提取失败或没有成功提取任何关键帧
- `2`: 部分成功（有部分关键帧提取失败）

## 测试

运行测试脚本验证功能：

```bash
python tools/test_extract_keyframes_simple.py
```

测试内容：
1. 文件命名约定验证
2. 模拟关键帧提取流程
3. 文件数量统计验证

## 迁移指南

如果要从旧的复杂方案迁移到新方案：

1. **更新主程序**：已自动使用 `extract_keyframes_simple.py`
2. **移除旧文件**：可以删除 `extract_keyframes.py` 和 `extraction_monitor.py`
3. **更新调用代码**：主程序已经更新，无需手动修改
4. **测试验证**：运行测试确保功能正常

## 总结

新的简化方案通过以下方式提升了系统的可靠性和性能：

1. **预先确定路径** -> 消除了文件名不一致的问题
2. **简化监听** -> 提高了监控的可靠性和效率  
3. **减少文件操作** -> 降低了出错概率
4. **清晰的逻辑** -> 更容易维护和调试

这个方案更加直接、高效，同时保持了多进程提取的性能优势。
