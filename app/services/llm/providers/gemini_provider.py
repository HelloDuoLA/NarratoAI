"""
原生Gemini API提供商实现

使用Google原生Gemini API进行视觉分析和文本生成
"""

import asyncio
import base64
import io
import requests
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import PIL.Image
from loguru import logger

from ..base import VisionModelProvider, TextModelProvider
from ..exceptions import APICallError, ContentFilterError


class GeminiVisionProvider(VisionModelProvider):
    """原生Gemini视觉模型提供商"""
    
    @property
    def provider_name(self) -> str:
        return "gemini"
    
    @property
    def supported_models(self) -> List[str]:
        return [
            "gemini-2.5-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash"
        ]
    
    def _initialize(self):
        """初始化Gemini特定设置"""
        if not self.base_url:
            self.base_url = "https://generativelanguage.googleapis.com/v1beta"
    
    async def analyze_images(self,
                           images: List[Union[str, Path, PIL.Image.Image]],
                           prompt: str,
                           batch_size: int = 10,
                           max_concurrent_tasks: int = 7,
                           **kwargs) -> List[str]:
        """
        使用原生Gemini API分析图片
        
        Args:
            images: 图片列表
            prompt: 分析提示词
            batch_size: 批处理大小
            max_concurrent_tasks: 最大并发任务数
            **kwargs: 其他参数
            
        Returns:
            分析结果列表
        """
        logger.info(f"开始分析 {len(images)} 张图片，使用原生Gemini API，最大并发任务数: {max_concurrent_tasks}")
        
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
    
    async def _analyze_batch(self, batch: List[PIL.Image.Image], prompt: str) -> str:
        """分析一批图片"""
        # 构建请求数据
        parts = [{"text": prompt}]
        
        # 添加图片数据
        for img in batch:
            img_data = self._image_to_base64(img)
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": img_data
                }
            })
        
        payload = {
            "systemInstruction": {
                "parts": [{"text": "你是一位专业的视觉内容分析师，请仔细分析图片内容并提供详细描述。"}]
            },
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 1.0,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 8192,
                "candidateCount": 1
            },
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH", 
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                }
            ]
        }
        
        # 发送API请求
        response_data = await self._make_api_call(payload)
        
        # 解析响应
        return self._parse_vision_response(response_data)

    # 新增: 用于处理带字幕的图片分析
    async def analyze_image_with_subtitle(self,
                           images: List[Union[str, Path, PIL.Image.Image]],
                           prompt: str,
                           **kwargs) -> List[str]:
        """
        使用原生Gemini API分析图片
        
        Args:
            images: 图片列表
            prompt: 分析提示词
            **kwargs: 其他参数
            
        Returns:
            分析结果列表
        """

        # 预处理图片
        processed_images = self._prepare_images(images)
        
        parts = [{"text": prompt}]
        
        # 添加图片数据
        for img in processed_images:
            img_data = self._image_to_base64(img)
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": img_data
                }
            })
        
        payload = {
            "systemInstruction": {
                "parts": [{"text": "你是一位专业的视觉内容分析师，请仔细分析图片内容并提供详细描述。"}]
            },
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 1.0,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 8192,
                "candidateCount": 1
            },
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH", 
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                }
            ]
        }
        
        # 发送API请求
        response_data = await self._make_api_call(payload)
        
        # 解析响应并返回
        return self._parse_vision_response(response_data)
        
    
    def _image_to_base64(self, img: PIL.Image.Image) -> str:
        """将PIL图片转换为base64编码"""
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='JPEG', quality=85)
        img_bytes = img_buffer.getvalue()
        return base64.b64encode(img_bytes).decode('utf-8')
    
    async def _make_api_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行原生Gemini API调用"""
        url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"
        
        response = await asyncio.to_thread(
            requests.post,
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "NarratoAI/1.0"
            },
            timeout=120
        )
        
        if response.status_code != 200:
            error = self._handle_api_error(response.status_code, response.text)
            raise error
        
        return response.json()
    
    def _parse_vision_response(self, response_data: Dict[str, Any]) -> str:
        """解析视觉分析响应"""
        if "candidates" not in response_data or not response_data["candidates"]:
            raise APICallError("原生Gemini API返回无效响应")
        
        candidate = response_data["candidates"][0]
        
        # 检查是否被安全过滤阻止
        if "finishReason" in candidate and candidate["finishReason"] == "SAFETY":
            safety_ratings = candidate.get("safetyRatings", [])
            logger.warning(f"内容被Gemini安全过滤器阻止，安全评级: {safety_ratings}")
            raise ContentFilterError("内容被Gemini安全过滤器阻止")
        
        # 检查是否因为长度限制停止
        if "finishReason" in candidate and candidate["finishReason"] == "MAX_TOKENS":
            logger.warning("Gemini因达到最大token限制而停止生成，内容可能被截断")
            # 继续处理，但记录警告
        
        # 记录完成原因（用于调试）
        finish_reason = candidate.get("finishReason", "UNKNOWN")
        if finish_reason != "STOP":
            logger.info(f"Gemini完成原因: {finish_reason}（非正常STOP）")
        
        if "content" not in candidate or "parts" not in candidate["content"]:
            raise APICallError("原生Gemini API返回内容格式错误")
        
        # 提取文本内容
        result = ""
        for part in candidate["content"]["parts"]:
            if "text" in part:
                result += part["text"]
        
        if not result.strip():
            raise APICallError("原生Gemini API返回空内容")
        
        return result


class GeminiTextProvider(TextModelProvider):
    """原生Gemini文本生成提供商"""
    
    @property
    def provider_name(self) -> str:
        return "gemini"
    
    @property
    def supported_models(self) -> List[str]:
        return [
            "gemini-2.5-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash"
        ]
    
    def _initialize(self):
        """初始化Gemini特定设置"""
        if not self.base_url:
            self.base_url = "https://generativelanguage.googleapis.com/v1beta"
    
    async def generate_text(self,
                          prompt: str,
                          system_prompt: Optional[str] = None,
                          temperature: float = 1.0,
                          max_tokens: Optional[int] = 30000,
                          response_format: Optional[str] = None,
                          **kwargs) -> str:
        """
        使用原生Gemini API生成文本
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 生成温度
            max_tokens: 最大token数
            response_format: 响应格式
            **kwargs: 其他参数
            
        Returns:
            生成的文本内容
        """
        # 构建请求数据
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 60000,
                "candidateCount": 1
            },
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", 
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                }
            ]
        }
        
        # 添加系统提示词
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }
        
        # 如果需要JSON格式，调整提示词和配置
        if response_format == "json":
            # 使用更温和的JSON格式约束
            enhanced_prompt = f"{prompt}\n\n请以JSON格式输出结果。"
            payload["contents"][0]["parts"][0]["text"] = enhanced_prompt
            # 移除可能导致问题的stopSequences
            # payload["generationConfig"]["stopSequences"] = ["```", "注意", "说明"]
        
        # 记录请求信息
        # logger.debug(f"Gemini文本生成请求: {payload}")

        # 发送API请求
        response_data = await self._make_api_call(payload)

        # 解析响应
        return self._parse_text_response(response_data)
    
    async def _make_api_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行原生Gemini API调用"""
        url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"
        
        response = await asyncio.to_thread(
            requests.post,
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "NarratoAI/1.0"
            },
            timeout=120
        )
        
        if response.status_code != 200:
            error = self._handle_api_error(response.status_code, response.text)
            raise error
        
        return response.json()
    
    def _parse_text_response(self, response_data: Dict[str, Any]) -> str:
        """解析文本生成响应"""
        logger.debug(f"Gemini API响应数据: {response_data}")

        if "candidates" not in response_data or not response_data["candidates"]:
            logger.error(f"Gemini API返回无效响应结构: {response_data}")
            raise APICallError("原生Gemini API返回无效响应")

        candidate = response_data["candidates"][0]
        logger.debug(f"Gemini候选响应: {candidate}")

        # 检查完成原因
        finish_reason = candidate.get("finishReason", "UNKNOWN")
        logger.debug(f"Gemini完成原因: {finish_reason}")

        # 检查是否被安全过滤阻止
        if finish_reason == "SAFETY":
            safety_ratings = candidate.get("safetyRatings", [])
            logger.warning(f"内容被Gemini安全过滤器阻止，安全评级: {safety_ratings}")
            raise ContentFilterError("内容被Gemini安全过滤器阻止")

        # 检查是否因为长度限制停止
        if finish_reason == "MAX_TOKENS":
            logger.warning("Gemini因达到最大token限制而停止生成，内容可能被截断")
            # 继续处理，但记录警告

        # 检查是否因为其他原因停止
        if finish_reason in ["RECITATION", "OTHER"]:
            logger.warning(f"Gemini因为{finish_reason}原因停止生成")
            raise APICallError(f"Gemini因为{finish_reason}原因停止生成")
        
        # 记录正常完成
        if finish_reason == "STOP":
            logger.debug("Gemini正常完成文本生成")
        elif finish_reason not in ["MAX_TOKENS"]:
            logger.info(f"Gemini以非标准原因完成: {finish_reason}")

        if "content" not in candidate:
            logger.error(f"Gemini候选响应中缺少content字段: {candidate}")
            raise APICallError("原生Gemini API返回内容格式错误")

        if "parts" not in candidate["content"]:
            logger.error(f"Gemini内容中缺少parts字段: {candidate['content']}")
            raise APICallError("原生Gemini API返回内容格式错误")

        # 提取文本内容
        result = ""
        for part in candidate["content"]["parts"]:
            if "text" in part:
                result += part["text"]

        if not result.strip():
            logger.error(f"Gemini API返回空文本内容，完整响应: {response_data}")
            raise APICallError("原生Gemini API返回空内容")

        logger.debug(f"Gemini成功生成内容，长度: {len(result)}")
        return result
