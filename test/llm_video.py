# 测试AI studio APIz 自带的视频分析能力
# 失败，最大体积不能超20MB
import os
from openai import OpenAI

client = OpenAI(
    api_key="fc2cabb304e83a50737f0486c8fd2465f701f13b",  # 含有 AI Studio 访问令牌的环境变量，https://aistudio.baidu.com/account/accessToken,
    base_url="https://aistudio.baidu.com/llm/lmapi/v3",  # aistudio 大模型 api 服务域名
)

completion = client.chat.completions.create(
    model="ernie-4.5-turbo-vl-preview",
    temperature=0.6,
    messages= [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "描述这个视频"
                },
                {
                    "type": "video_url",
                    "video_url": {
                        "url": "https://bucket-demo-01.gz.bcebos.com/video/sea.mov", 
                        "fps": 1 
                    }
                }
            ]
        }
    ],
    stream=True
)

for chunk in completion:
    if (len(chunk.choices) > 0):
        print(chunk.choices[0].delta.content, end="", flush=True)