"""
ERNIE AI Studio API提供商实现

支持百度AI Studio的文本生成和视觉模型
"""

import asyncio
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import base64
import io
from openai import OpenAI
from loguru import logger
import PIL.Image

from ..base import VisionModelProvider, TextModelProvider
from ..exceptions import APICallError


class ErnieAIStudioVisionProvider(VisionModelProvider):
    """ERNIE AI Studio视觉模型提供商"""
    
    @property
    def provider_name(self) -> str:
        return "ernie_ai_studio"
    
    @property
    def supported_models(self) -> List[str]:
        return [
            "ernie-4.5-turbo-vl-preview",
            "ernie-4.5-vl-28b-a3b",
            "ernie-4.5-turbo-vl-32k"
        ]
    
    def _initialize(self):
        """初始化ERNIE AI Studio客户端"""
        if not self.base_url:
            self.base_url = "https://aistudio.baidu.com/llm/lmapi/v3"
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    async def analyze_images(self,
                           images: List[Union[str, Path, PIL.Image.Image]],
                           prompt: str,
                           batch_size: int = 10,
                           max_concurrent_tasks: int = 2,
                           **kwargs) -> List[str]:
        """
        使用ERNIE AI Studio API分析图片
        
        Args:
            images: 图片路径列表或PIL图片对象列表
            prompt: 分析提示词
            batch_size: 批处理大小
            max_concurrent_tasks: 最大并发任务数
            **kwargs: 其他参数
            
        Returns:
            分析结果列表
        """
        logger.info(f"开始分析 {len(images)} 张图片，使用百度大模型，最大并发任务数: {max_concurrent_tasks}")
        
        # 预处理图片
        processed_images = self._prepare_images(images)
        
        # 创建信号量来限制并发数
        semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        # 分批处理
        async def process_batch_with_semaphore(batch_index: int, batch: List[PIL.Image.Image]) -> tuple:
            async with semaphore:
                logger.info(f"处理第 {batch_index + 1} 批，共 {len(batch)} 张图片")
                try:
                    result = await self._analyze_batch(batch, prompt)
                    return batch_index, result
                except Exception as e:
                    logger.error(f"批次 {batch_index + 1} 处理失败: {str(e)}")
                    return batch_index, f"批次处理失败: {str(e)}"
        
        # 创建所有批次的任务
        tasks = []
        for i in range(0, len(processed_images), batch_size):
            batch = processed_images[i:i + batch_size]
            batch_index = i // batch_size
            task = process_batch_with_semaphore(batch_index, batch)
            tasks.append(task)
        
        # 并发执行所有任务
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 按批次顺序整理结果
        results = [None] * len(tasks)
        for task_result in task_results:
            if isinstance(task_result, Exception):
                logger.error(f"任务执行异常: {str(task_result)}")
                # 找到第一个空位置放置错误结果
                for i in range(len(results)):
                    if results[i] is None:
                        results[i] = f"任务执行异常: {str(task_result)}"
                        break
            else:
                batch_index, result = task_result
                results[batch_index] = result
        
        # 过滤掉None值并返回
        return [result for result in results if result is not None]
    
        # 新增: 用于处理带字幕的图片分析
    async def analyze_image_with_subtitle(self,
                           images: List[Union[str, Path, PIL.Image.Image]],
                           prompt: str,
                           **kwargs) -> List[str]:
        """
        使用ERNIE AI Studio API分析图片
        
        Args:
            images: 图片列表
            prompt: 分析提示词
            **kwargs: 其他参数
            
        Returns:
            分析结果列表
        """
        
        # 预处理图片
        processed_images = self._prepare_images(images)
        
        # 将多张图片组合成一个请求
        content_parts = [{"type": "text", "text": prompt}]
            
        # 添加所有图片
        for image in processed_images:
            image_base64 = self._image_to_base64(image)
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            })
            
        messages = [{"role": "user", "content": content_parts}]
            
        # 发送API请求
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model_name,
            messages=messages,
            max_tokens=8192
        )
        
        if response.choices and len(response.choices) > 0:
            content = response.choices[0].message.content
            logger.debug(f"ERNIE AI Studio批量分析成功，图片数量: {len(images)}")
            return content
        else:
            raise APICallError("ERNIE AI Studio API返回空响应")

        
        # 过滤掉None值并返回
        return [result for result in results if result is not None]
    
    async def _analyze_batch(self, images: List[PIL.Image.Image], prompt: str) -> str:
        """
        分析一批图片，返回统一的分析结果
        
        Args:
            images: PIL图片对象列表
            prompt: 分析提示词
            
        Returns:
            批量分析的综合结果
        """
        try:
            # 将多张图片组合成一个请求
            content_parts = [{"type": "text", "text": prompt}]
            
            # 添加所有图片
            for image in images:
                image_base64 = self._image_to_base64(image)
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                })
            
            messages = [{"role": "user", "content": content_parts}]
            
            # 发送API请求
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model_name,
                messages=messages,
                max_tokens=8192
            )
            
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                logger.debug(f"ERNIE AI Studio批量分析成功，图片数量: {len(images)}")
                return content
            else:
                raise APICallError("ERNIE AI Studio API返回空响应")
                
        except Exception as e:
            logger.error(f"ERNIE AI Studio批量分析失败: {str(e)}")
            raise APICallError(f"批量分析失败: {str(e)}")
    
    def _image_to_base64(self, image: PIL.Image.Image) -> str:
        """将PIL图片转换为base64编码"""
        buffered = io.BytesIO()
        # 转换为RGB格式（如果需要）
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(buffered, format="JPEG", quality=85)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return img_str
    
    async def _make_api_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行API调用 - 由于使用OpenAI SDK，这个方法主要用于兼容基类"""
        # 这个方法在ERNIE AI Studio提供商中不直接使用，因为我们使用OpenAI SDK
        # 但为了兼容基类接口，保留此方法
        pass

    

class ErnieAIStudioTextProvider(TextModelProvider):
    """ERNIE AI Studio文本生成提供商"""
    
    @property
    def provider_name(self) -> str:
        return "ernie_ai_studio"
    
    @property
    def supported_models(self) -> List[str]:
        return [
            "ernie-4.5-turbo-vl-preview",
            "ernie-4.5-vl-28b-a3b",
            "ernie-4.5-turbo-vl-32k",
            "ernie-4.5-turbo-128k"
        ]
    
    def _initialize(self):
        """初始化ERNIE AI Studio客户端"""
        if not self.base_url:
            self.base_url = "https://aistudio.baidu.com/llm/lmapi/v3"
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    async def generate_text(self,
                          prompt: str,
                          system_prompt: Optional[str] = None,
                          temperature: float = 1.0,
                          max_tokens: Optional[int] = None,
                          response_format: Optional[str] = None,
                          **kwargs) -> str:
        """
        使用ERNIE AI Studio API生成文本
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 生成温度
            max_tokens: 最大token数
            response_format: 响应格式 ('json' 或 None)
            **kwargs: 其他参数
            
        Returns:
            生成的文本内容
        """
        # 构建消息列表
        messages = self._build_messages(prompt, system_prompt)
        
        # 构建请求参数
        request_params = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature
        }
        
        # if max_tokens:
        #     request_params["max_tokens"] = max_tokens
        
        # 处理JSON格式输出 - ERNIE通常不直接支持response_format
        if response_format == "json":
            messages[-1]["content"] += "\n\n请确保输出严格的JSON格式，不要包含任何其他文字或标记。"
        
        try:
            # 发送API请求
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                max_tokens=12000,
                **request_params
            )
            
            # 提取生成的内容
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                
                # 对于JSON格式，清理输出
                if response_format == "json":
                    content = self._clean_json_output(content)
                
                logger.debug(f"ERNIE AI Studio API调用成功，消耗tokens: {response.usage.total_tokens if response.usage else 'N/A'}")
                return content
            else:
                raise APICallError("ERNIE AI Studio API返回空响应")
                
        except Exception as e:
            logger.error(f"ERNIE AI Studio API调用失败: {str(e)}")
            raise APICallError(f"ERNIE AI Studio API调用失败: {str(e)}")
    
    def _clean_json_output(self, output: str) -> str:
        """清理JSON输出，移除markdown标记等"""
        import re
        
        # 移除可能的markdown代码块标记
        output = re.sub(r'^```json\s*', '', output, flags=re.MULTILINE)
        output = re.sub(r'^```\s*$', '', output, flags=re.MULTILINE)
        output = re.sub(r'^```.*$', '', output, flags=re.MULTILINE)
        
        # 移除前后空白字符
        output = output.strip()
        
        return output
    
    async def _make_api_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行API调用 - 由于使用OpenAI SDK，这个方法主要用于兼容基类"""
        # 这个方法在ERNIE AI Studio提供商中不直接使用，因为我们使用OpenAI SDK
        # 但为了兼容基类接口，保留此方法
        pass
