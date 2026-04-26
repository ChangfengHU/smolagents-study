from __future__ import annotations

import requests
from typing import Any, Literal
from smolagents.models import Model, ChatMessage, MessageRole, TokenUsage
from smolagents.tools import Tool


class VyibcModel(Model):
    """
    对接 Vyibc (Auto Content API) 的文本生成模型类。
    支持 grok, vertex 等供应方。
    """

    def __init__(
        self,
        provider: Literal["grok", "vertex"] = "grok",
        model: str | None = None,
        base_url: str = "https://images.vyibc.com",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.provider = provider
        # 如果不传 model，API 会走默认模型。用户建议优先使用 grok-4.20
        self.model_id = model or ("grok-4.20" if provider == "grok" else "imagen-4.0-ultra-generate-001")
        self.base_url = base_url

    def generate(
        self,
        messages: list[dict[str, Any]] | list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, Any] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs,
    ) -> ChatMessage:
        # 准备消息列表。目前 API 是单 prompt 输入，我们将上下文拼接
        completion_kwargs = self._prepare_completion_kwargs(messages, stop_sequences, response_format, tools_to_call_from, **kwargs)
        actual_messages = completion_kwargs["messages"]
        
        full_prompt = ""
        for msg in actual_messages:
            role = msg["role"]
            content = msg["content"]
            full_prompt += f"{role}: {content}\n"
        
        payload = {
            "provider": self.provider,
            "model": self.model_id,
            "prompt": full_prompt.strip(),
        }

        # 调用 vyibc 统一文本生成接口
        response = requests.post(
            f"{self.base_url}/v1beta/text:generate",
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        result = response.json()

        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=result.get("text", ""),
            raw=result,
            token_usage=TokenUsage(input_tokens=0, output_tokens=0) # 接口暂未返回 token 统计
        )


class VyibcImageTool(Tool):
    """
    对接 Vyibc (Auto Content API) 的图像生成工具。
    """
    name = "vyibc_image_generator"
    description = "使用 Vyibc API 根据提示词生成图像。返回生成图像的 URL 列表。"
    inputs = {
        "prompt": {
            "type": "string",
            "description": "用于生成图像的详细描述性提示词。",
        },
        "provider": {
            "type": "string",
            "description": "供货商名称，'vertex' 或 'grok'。默认为 'vertex'。",
            "nullable": True,
        },
        "model": {
            "type": "string",
            "description": "具体的模型名称。'vertex' 默认为 'imagen-4.0-ultra-generate-001'，'grok' 默认为 'grok-imagine-image'。",
            "nullable": True,
        },
        "n": {
            "type": "integer",
            "description": "生成的图像数量，默认为 1。",
            "nullable": True,
        }
    }
    output_type = "any"

    def __init__(self, base_url: str = "https://images.vyibc.com", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = base_url

    def forward(
        self,
        prompt: str,
        provider: str = "vertex",
        model: str | None = None,
        n: int = 1
    ) -> list[str]:
        payload = {
            "provider": provider,
            "prompt": prompt,
            "n": n,
            "storage_backend": "oss" # 默认使用 OSS 存储以获取永久链接
        }
        if model:
            payload["model"] = model
        elif provider == "vertex":
            payload["model"] = "imagen-4.0-ultra-generate-001"
        elif provider == "grok":
            payload["model"] = "grok-imagine-image-pro"

        response = requests.post(
            f"{self.base_url}/v1beta/images:generate",
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        
        return result.get("image_urls", [])
