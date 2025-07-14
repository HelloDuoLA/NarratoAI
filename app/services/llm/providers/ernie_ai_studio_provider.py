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
            "ernie-4.5-vl-28b-a3b"
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
                           **kwargs) -> List[str]:
        """
        使用ERNIE AI Studio API分析图片
        
        Args:
            images: 图片路径列表或PIL图片对象列表
            prompt: 分析提示词
            batch_size: 批处理大小
            **kwargs: 其他参数
            
        Returns:
            分析结果列表
        """
        logger.info(f"开始分析 {len(images)} 张图片，使用百度大模型")
        
        # 预处理图片
        processed_images = self._prepare_images(images)
        
        # 分批处理图片
        results = []
        for i in range(0, len(processed_images), batch_size):
            batch_images = processed_images[i:i+batch_size]
            
            try:
                batch_results = await self._analyze_image_batch(batch_images, prompt, **kwargs)
                results.extend(batch_results)
                
            except Exception as e:
                logger.error(f"批次 {i//batch_size + 1} 分析失败: {str(e)}")
                # 为失败的批次添加错误信息
                for _ in batch_images:
                    results.append(f"图片分析失败: {str(e)}")
        
        return results
    
    async def _analyze_image_batch(self,
                                 images: List[PIL.Image.Image],
                                 prompt: str,
                                 **kwargs) -> List[str]:
        """分析一批图片"""
        results = []
        
        for image in images:
            try:
                # 将图片转换为base64编码
                image_base64 = self._image_to_base64(image)
                
                # 构建消息
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ]
                
                # 发送API请求
                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=self.model_name,
                    messages=messages,
                    max_tokens=4000
                )
                
                if response.choices and len(response.choices) > 0:
                    content = response.choices[0].message.content
                    results.append(content)
                    logger.debug(f"ERNIE AI Studio图片分析成功")
                else:
                    results.append("ERNIE AI Studio API返回空响应")
                    
            except Exception as e:
                logger.error(f"ERNIE AI Studio图片分析失败: {str(e)}")
                results.append(f"图片分析失败: {str(e)}")
        
        return results
    
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
        """执行API调用"""
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
            "ernie-4.5-vl-28b-a3b"
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
        
        if max_tokens:
            request_params["max_tokens"] = max_tokens
        
        # 处理JSON格式输出 - ERNIE通常不直接支持response_format
        if response_format == "json":
            messages[-1]["content"] += "\n\n请确保输出严格的JSON格式，不要包含任何其他文字或标记。"
        
        try:
            # 发送API请求
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
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
        pass
