from __future__ import annotations

"""微信公众号文章生成示例。

这个脚本会完成 4 件事：
1. 读取你在文件顶部写好的配置，比如文章主题、文风、插图数量、插图风格。
2. 调用 xAI 文本模型，先生成一篇结构化的文章草稿。
3. 调用 xAI 生图模型，为封面和每个正文小节生成配图。
4. 把结果写成 markdown、html、json，方便你直接查看或二次编辑。

如果你是新手，优先看这几个位置：
- SCRIPT_PRESET_INDEX: 选择第几套预设创意。
- SCRIPT_PRESET_FILE: 预设创意 json 文件路径。
- 项目根目录 `.env`: 在这里写 `XAI_API_KEY=...`。
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import mimetypes
import os
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency for local runs
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"


DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_TEXT_MODEL = "grok-4-fast-non-reasoning"
DEFAULT_IMAGE_MODEL = "grok-imagine-image"
DEFAULT_OSS_ENDPOINT = "http://oss-cn-hangzhou.aliyuncs.com"
DEFAULT_OSS_BUCKET = "articel"


class XAIAPIError(RuntimeError):
    """xAI 接口返回错误时抛出的异常。"""


@dataclass(frozen=True)
class XAIConfig:
    """调用 xAI 接口时需要的基础配置。"""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    text_model: str = DEFAULT_TEXT_MODEL
    image_model: str = DEFAULT_IMAGE_MODEL
    timeout_seconds: int = 180
    retry_attempts: int = 2
    retry_backoff_seconds: float = 1.5


@dataclass(frozen=True)
class ArticleRequest:
    """描述“你想生成什么文章”的输入参数。"""

    topic: str
    audience: str = "Chinese WeChat readers who value clarity, usefulness, and strong storytelling"
    tone: str = "warm, sharp, and trustworthy"
    sections: int = 4
    use_web_search: bool = False
    image_style: str = "premium editorial illustration, cinematic lighting, clean composition, no text overlay"
    aspect_ratio: str = "16:9"
    resolution: str = "2k"


@dataclass(frozen=True)
class CreativePreset:
    """一套可复用的文章创意预设。"""

    name: str
    topic: str
    audience: str = ArticleRequest.audience
    tone: str = ArticleRequest.tone
    section_count: int = ArticleRequest.sections
    use_web_search: bool = False
    image_style: str = ArticleRequest.image_style
    aspect_ratio: str = ArticleRequest.aspect_ratio
    resolution: str = ArticleRequest.resolution

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CreativePreset":
        """把 json 里的单条预设转换成 dataclass。"""

        section_count = payload.get("section_count", ArticleRequest.sections)
        use_web_search = payload.get("use_web_search", False)

        if not isinstance(section_count, int) or section_count < 1:
            raise ValueError(f"Invalid section_count in preset: {section_count!r}")
        if not isinstance(use_web_search, bool):
            raise ValueError(f"Invalid use_web_search in preset: {use_web_search!r}")

        return cls(
            name=_require_string(payload, "name"),
            topic=_require_string(payload, "topic"),
            audience=_require_string(payload, "audience"),
            tone=_require_string(payload, "tone"),
            section_count=section_count,
            use_web_search=use_web_search,
            image_style=_require_string(payload, "image_style"),
            aspect_ratio=_require_string(payload, "aspect_ratio"),
            resolution=_require_string(payload, "resolution"),
        )

    def to_article_request(self) -> ArticleRequest:
        """把预设转换成真正参与生成的 ArticleRequest。"""

        return ArticleRequest(
            topic=self.topic,
            audience=self.audience,
            tone=self.tone,
            sections=self.section_count,
            use_web_search=self.use_web_search,
            image_style=self.image_style,
            aspect_ratio=self.aspect_ratio,
            resolution=self.resolution,
        )


# =========================
# 这里是你最常改的配置区域
# =========================
# 这个脚本现在默认由“预设创意 json”驱动。
# 你平时只需要改下面两个变量，然后直接运行 python 文件即可。
SCRIPT_PRESET_FILE = Path(__file__).with_name("grok_wechat_article_presets.json")
# 按 1 开始计数。比如填 3，就使用 json 里的第 3 套创意。
SCRIPT_PRESET_INDEX = 5
# API Key 不再建议写死在代码里。
# 请在项目根目录 .env 中写一行：
# XAI_API_KEY=你的新 key
# 如果这里保持 None，脚本会通过 load_dotenv() + resolve_api_key() 从 .env / 环境变量读取。
SCRIPT_API_KEY: str | None = None
# SCRIPT_BASE_URL / SCRIPT_TEXT_MODEL / SCRIPT_IMAGE_MODEL:
# 一般不用改，除非你明确知道自己要切换接口地址或模型。
SCRIPT_BASE_URL = DEFAULT_BASE_URL
SCRIPT_TEXT_MODEL = DEFAULT_TEXT_MODEL
SCRIPT_IMAGE_MODEL = DEFAULT_IMAGE_MODEL
# SCRIPT_TIMEOUT_SECONDS: 单次网络请求最多等多久。
# 如果你觉得“卡住太久”，可以先改成 30 或 60 方便排查。
SCRIPT_TIMEOUT_SECONDS = 300
# SCRIPT_RETRY_ATTEMPTS: 网络失败后最多重试几次。
SCRIPT_RETRY_ATTEMPTS = 2
# SCRIPT_RETRY_BACKOFF_SECONDS: 每次重试前等待多久，后续会按次数递增。
SCRIPT_RETRY_BACKOFF_SECONDS = 1.5
# SCRIPT_IMAGE_MAX_CONCURRENCY: 图片并发生成上限。
SCRIPT_IMAGE_MAX_CONCURRENCY = int(os.getenv("SCRIPT_IMAGE_MAX_CONCURRENCY", "6"))
# SCRIPT_IMAGE_FALLBACK_MODELS: 主供应商（xAI）失败后的候选模型（逗号分隔）。
SCRIPT_IMAGE_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv("SCRIPT_IMAGE_FALLBACK_MODELS", "grok-imagine-image-pro").split(",")
    if model.strip()
]
# SCRIPT_IMAGE_FALLBACK_API_URL: 供应商兜底接口（统一生图 API）。
SCRIPT_IMAGE_FALLBACK_API_URL = os.getenv("SCRIPT_IMAGE_FALLBACK_API_URL", "https://images.vyibc.com/api/v1beta/images:generate")
# SCRIPT_IMAGE_FALLBACK_CANDIDATES: 兜底候选，格式 provider:model,provider:model...
# 生图候选实测指标（2026-04-28，单轮基准，仅作排序参考）：
# - grok:grok-imagine-image -> 8.08s (ok)
# - vertex:imagen-4.0-generate-001 -> 21.93s (ok)
# - vertex:imagen-4.0-fast-generate-001 -> 18.74s (ok)
# - vertex:imagen-4.0-ultra-generate-001 -> 26.55s (ok)
SCRIPT_IMAGE_FALLBACK_CANDIDATES = [
    candidate.strip()
    for candidate in os.getenv(
        "SCRIPT_IMAGE_FALLBACK_CANDIDATES",
        "grok:grok-imagine-image,vertex:imagen-4.0-generate-001,vertex:imagen-4.0-fast-generate-001,vertex:imagen-4.0-ultra-generate-001",
    ).split(",")
    if candidate.strip()
]
# SCRIPT_TEXT_GATEWAY_API_URL: 统一文本接口。
SCRIPT_TEXT_GATEWAY_API_URL = os.getenv("SCRIPT_TEXT_GATEWAY_API_URL", "https://images.vyibc.com/api/v1beta/text:generate")
# SCRIPT_TEXT_GATEWAY_CANDIDATES: 文本候选，格式 provider:model,provider:model...
# 文本候选实测指标（2026-04-28，单轮基准，仅作排序参考）：
# - grok:grok-4-fast-non-reasoning -> 8.17s (ok)
# - vertex:gemini-2.5-flash -> 25.35s (ok)
# - grok:grok-3-mini -> 27.12s (ok)
# - grok:grok-3 -> 21.57s (ok)
# - vertex:gemini-2.5-pro -> 23.17s (ok, 按用户 curl 复测)
SCRIPT_TEXT_GATEWAY_CANDIDATES = [
    candidate.strip()
    for candidate in os.getenv(
        "SCRIPT_TEXT_GATEWAY_CANDIDATES",
        "grok:grok-4-fast-non-reasoning,vertex:gemini-2.5-flash,grok:grok-3-mini,grok:grok-3,vertex:gemini-2.5-pro",
    ).split(",")
    if candidate.strip()
]
# generation_profile: 生成策略（speed | balanced | quality），用于同时切换文本与生图候选优先级。
SCRIPT_GENERATION_PROFILE = os.getenv("SCRIPT_GENERATION_PROFILE", "balanced").strip().lower()
SCRIPT_GENERATION_PROFILES: dict[str, dict[str, list[str]]] = {
    "speed": {
        "text_candidates": [
            "grok:grok-4-fast-non-reasoning",
            "grok:grok-3-mini",
            "vertex:gemini-2.5-flash",
        ],
        "image_candidates": [
            "grok:grok-imagine-image",
            "vertex:imagen-4.0-fast-generate-001",
            "vertex:imagen-4.0-generate-001",
        ],
    },
    "balanced": {
        "text_candidates": [
            "grok:grok-4-fast-non-reasoning",
            "vertex:gemini-2.5-flash",
            "grok:grok-3-mini",
            "grok:grok-3",
            "vertex:gemini-2.5-pro",
        ],
        "image_candidates": [
            "grok:grok-imagine-image",
            "vertex:imagen-4.0-fast-generate-001",
            "vertex:imagen-4.0-generate-001",
            "vertex:imagen-4.0-ultra-generate-001",
        ],
    },
    "quality": {
        "text_candidates": [
            "vertex:gemini-2.5-pro",
            "grok:grok-4-fast-non-reasoning",
            "vertex:gemini-2.5-flash",
        ],
        "image_candidates": [
            "vertex:imagen-4.0-ultra-generate-001",
            "vertex:imagen-4.0-generate-001",
            "grok:grok-imagine-image",
        ],
    },
}
# 与 generation_profile 对齐的提示词强度档位。
SCRIPT_PROMPT_PROFILE = os.getenv("SCRIPT_PROMPT_PROFILE", "").strip().lower()
TEXT_PROMPT_PROFILE_HINTS: dict[str, str] = {
    "speed": (
        "Prioritize concise output and strict schema compliance. "
        "If trade-offs are needed, preserve JSON validity and section structure first."
    ),
    "balanced": (
        "Balance readability and detail. Keep each section practical and avoid overlong digressions."
    ),
    "quality": (
        "Prioritize depth, clarity, and narrative coherence. "
        "Each section should include one concrete scenario and one actionable recommendation."
    ),
}
IMAGE_PROMPT_PROFILE_SUFFIX: dict[str, str] = {
    "speed": (
        "clean composition, readable subject separation, no text overlay, no watermark, no logo"
    ),
    "balanced": (
        "cinematic editorial style, natural lighting, consistent visual storytelling, "
        "no text overlay, no watermark, no logo"
    ),
    "quality": (
        "premium editorial quality, rich micro-details, physically plausible lighting, "
        "natural textures, no text overlay, no watermark, no logo, no distorted hands"
    ),
}
# 文本网关专项超时与重试（与 xAI 调用分离），用于缩短拥塞场景耗时。
SCRIPT_TEXT_GATEWAY_TIMEOUT_SECONDS = int(os.getenv("SCRIPT_TEXT_GATEWAY_TIMEOUT_SECONDS", "45"))
SCRIPT_TEXT_GATEWAY_RETRY_ATTEMPTS = int(os.getenv("SCRIPT_TEXT_GATEWAY_RETRY_ATTEMPTS", "1"))
SCRIPT_TEXT_GATEWAY_RETRY_BACKOFF_SECONDS = float(os.getenv("SCRIPT_TEXT_GATEWAY_RETRY_BACKOFF_SECONDS", "1.0"))
# 是否启用“直连 xAI 文本”最终兜底。默认关闭，以避免拥塞时长尾耗时。
SCRIPT_TEXT_ENABLE_DIRECT_XAI_FALLBACK = os.getenv("SCRIPT_TEXT_ENABLE_DIRECT_XAI_FALLBACK", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# 统一生图接口的落地模式。local 由 images.vyibc.com 静态资源直接公网访问，通常更快。
SCRIPT_IMAGE_GATEWAY_STORAGE_BACKEND = os.getenv("SCRIPT_IMAGE_GATEWAY_STORAGE_BACKEND", "local")
# SCRIPT_STORAGE_MODE: 产物存储模式。local=仅本地输出，remote=上传 OSS 并替换引用。
SCRIPT_STORAGE_MODE = os.getenv("GROK_WECHAT_STORAGE_MODE", "remote")
# SCRIPT_OUTPUT_DIR: 输出目录。
# 留空时，脚本会自动按“主题 + 时间戳”创建新目录。
SCRIPT_OUTPUT_DIR = ""


@dataclass(frozen=True)
class ArticleSection:
    """文章中单个正文小节的数据结构。"""

    heading: str
    hook: str
    paragraphs: list[str]
    bullets: list[str]
    takeaway: str
    image_prompt: str
    image_alt: str
    image_caption: str


@dataclass(frozen=True)
class ArticleDraft:
    """文本模型返回的整篇文章草稿。"""

    title: str
    subtitle: str
    summary: str
    cover_image_prompt: str
    cover_image_alt: str
    intro_paragraphs: list[str]
    sections: list[ArticleSection]
    conclusion_title: str
    conclusion_paragraphs: list[str]
    call_to_action: str
    tags: list[str]

    @classmethod
    def from_dict(cls, payload: dict[str, Any], expected_sections: int) -> "ArticleDraft":
        """把模型返回的原始字典转换成强类型对象，并顺手做格式校验。"""

        sections_data = _require_list(payload, "sections", min_items=expected_sections)
        if len(sections_data) != expected_sections:
            raise ValueError(f"Expected {expected_sections} sections, got {len(sections_data)}.")

        sections = [
            ArticleSection(
                heading=_require_string(section, "heading"),
                hook=_require_string(section, "hook"),
                paragraphs=_require_list_of_strings(section, "paragraphs", min_items=2),
                bullets=_require_list_of_strings(section, "bullets", min_items=3),
                takeaway=_require_string(section, "takeaway"),
                image_prompt=_require_string(section, "image_prompt"),
                image_alt=_require_string(section, "image_alt"),
                image_caption=_require_string(section, "image_caption"),
            )
            for section in sections_data
        ]

        return cls(
            title=_require_string(payload, "title"),
            subtitle=_require_string(payload, "subtitle"),
            summary=_require_string(payload, "summary"),
            cover_image_prompt=_require_string(payload, "cover_image_prompt"),
            cover_image_alt=_require_string(payload, "cover_image_alt"),
            intro_paragraphs=_require_list_of_strings(payload, "intro_paragraphs", min_items=1),
            sections=sections,
            conclusion_title=_require_string(payload, "conclusion_title"),
            conclusion_paragraphs=_require_list_of_strings(payload, "conclusion_paragraphs", min_items=1),
            call_to_action=_require_string(payload, "call_to_action"),
            tags=_require_list_of_strings(payload, "tags", min_items=3),
        )


@dataclass(frozen=True)
class GeneratedImage:
    """一张已经生成好的图片及其元信息。"""

    prompt: str
    source_url: str
    alt_text: str
    caption: str
    revised_prompt: str | None = None
    local_path: str | None = None


@dataclass(frozen=True)
class ArticleBundle:
    """最终产物集合：文章、图片、markdown、html 都放在这里。"""

    request: ArticleRequest
    draft: ArticleDraft
    cover_image: GeneratedImage
    section_images: list[GeneratedImage]
    markdown: str
    html: str
    output_dir: str
    public_urls: dict[str, str] | None = None


@dataclass(frozen=True)
class OSSConfig:
    """阿里云 OSS 上传配置。"""

    access_key_id: str
    access_key_secret: str
    bucket_name: str
    endpoint: str = DEFAULT_OSS_ENDPOINT
    key_prefix: str = "generated_articles"
    public_base_url: str | None = None


@dataclass(frozen=True)
class ImageFallbackCandidate:
    provider: str
    model: str


@dataclass(frozen=True)
class TextGatewayCandidate:
    provider: str
    model: str


class XAIHttpClient:
    """对 requests 的简单封装，统一处理鉴权、重试和下载。"""

    def __init__(self, config: XAIConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
                "Connection": "close",
            }
        )

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """向 xAI 发送 JSON 请求，并在失败时自动重试。"""

        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                log_progress(
                    f"HTTP POST {self.config.base_url}{path} "
                    f"(attempt {attempt}/{self.config.retry_attempts}, timeout={self.config.timeout_seconds}s)"
                )
                response = self.session.post(
                    f"{self.config.base_url}{path}",
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
                log_progress(f"HTTP {response.status_code} from {path}")
                data = _decode_json(response)
                if response.status_code >= 400:
                    if _is_retryable_http_status(response.status_code) and attempt < self.config.retry_attempts:
                        backoff_seconds = self.config.retry_backoff_seconds * attempt + random.uniform(0.2, 0.8)
                        log_progress(
                            f"HTTP {response.status_code} from {path}, retrying after {backoff_seconds:.1f}s "
                            f"(attempt {attempt}/{self.config.retry_attempts})"
                        )
                        time.sleep(backoff_seconds)
                        continue
                    raise XAIAPIError(_format_http_error(response.status_code, data))
                if isinstance(data, dict) and data.get("error"):
                    raise XAIAPIError(f"xAI API error: {data['error']}")
                return data
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                log_progress(f"Request failed for {path}: {exc}")
                if attempt == self.config.retry_attempts:
                    break
                log_progress(f"Retrying {path} after {self.config.retry_backoff_seconds * attempt:.1f}s")
                time.sleep(self.config.retry_backoff_seconds * attempt)

        raise XAIAPIError(f"xAI API request failed after retries: {last_error}") from last_error

    def download_binary(self, url: str, destination: Path) -> Path:
        """下载图片二进制内容，并根据响应头或 URL 自动补后缀。"""

        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                log_progress(
                    f"Downloading image to {destination.parent.name}/{destination.name} "
                    f"(attempt {attempt}/{self.config.retry_attempts})"
                )
                response = self.session.get(url, timeout=self.config.timeout_seconds)
                response.raise_for_status()
                extension = _guess_image_extension(url, response.headers.get("Content-Type", ""))
                target = destination.with_suffix(extension)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(response.content)
                log_progress(f"Saved image: {target}")
                return target
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                log_progress(f"Image download failed: {exc}")
                if attempt == self.config.retry_attempts:
                    break
                log_progress(f"Retrying image download after {self.config.retry_backoff_seconds * attempt:.1f}s")
                time.sleep(self.config.retry_backoff_seconds * attempt)

        raise XAIAPIError(f"Image download failed after retries: {last_error}") from last_error


class XAITextGenerationTool:
    """负责“生成文章草稿”这一步。"""

    def __init__(self, client: XAIHttpClient):
        self.client = client

    def generate_article_draft(self, request: ArticleRequest) -> ArticleDraft:
        """调用文本模型生成结构化文章，然后把 JSON 转成 ArticleDraft。"""

        log_progress(f"Generating article draft for topic: {request.topic}")

        # 这里要求模型严格按 JSON Schema 返回，方便后续程序稳定解析。
        payload = {
            "model": self.client.config.text_model,
            "input": [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": self._build_user_prompt(request)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "wechat_article",
                    "schema": self._build_schema(request.sections),
                    "strict": True,
                }
            },
        }
        if request.use_web_search:
            # 只有在你打开联网搜索时，才允许模型使用搜索工具。
            payload["tools"] = [{"type": "web_search"}]
            payload["include"] = ["no_inline_citations"]

        response = self.client.post_json("/responses", payload)
        raw_text = extract_response_output_text(response)

        try:
            # 模型先返回字符串，这里把它转成 Python 字典。
            article_data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise XAIAPIError(f"Structured article response was not valid JSON: {raw_text[:500]}") from exc

        try:
            # 再把字典转成更好用的 dataclass。
            draft = ArticleDraft.from_dict(article_data, expected_sections=request.sections)
            log_progress("Article draft generated successfully")
            return draft
        except (TypeError, ValueError, KeyError) as exc:
            raise XAIAPIError(f"Structured article response did not match the expected schema: {article_data}") from exc

    @staticmethod
    def _build_system_prompt() -> str:
        """系统提示词：规定模型的角色和总体写作原则。"""

        return (
            "You are a senior WeChat public-account editor and visual director. "
            "Write polished Simplified Chinese copy for a high-quality article package. "
            "Do not fabricate statistics, dates, or named sources. If certainty is low, stay general and practical. "
            "Keep prose vivid but restrained, avoid emoji, avoid markdown fences, and keep every image prompt in English."
        )

    @staticmethod
    def _build_user_prompt(request: ArticleRequest) -> str:
        """用户提示词：把你配置的主题、文风、插图风格等告诉模型。"""

        today = datetime.now().strftime("%Y-%m-%d")
        search_guidance = (
            "Use web search for current facts and express dates explicitly."
            if request.use_web_search
            else "Do not rely on live facts; make the article evergreen and insight-driven."
        )
        return (
            f"Create a complete Chinese WeChat article package about: {request.topic}\n"
            f"Audience: {request.audience}\n"
            f"Tone: {request.tone}\n"
            f"Section count: {request.sections}\n"
            f"Image style guidance: {request.image_style}\n"
            f"Today's date: {today}\n"
            f"Guidance: {search_guidance}\n"
            "Requirements:\n"
            "1. The article must be suitable for a polished public-account post.\n"
            "2. Keep the Chinese article natural, specific, and readable on mobile.\n"
            "3. The title should be strong but not clickbait.\n"
            "4. The subtitle should clarify the value proposition.\n"
            "5. The intro should create immediate curiosity.\n"
            "6. Each section needs a hook, two or three concise paragraphs, three to five scannable bullets, and a one-line takeaway.\n"
            "7. The cover image prompt and section image prompts must be in English, visually concrete, and should explicitly avoid text overlays.\n"
            "8. Follow the image style guidance consistently across the cover and section illustrations.\n"
            "9. Keep the final package self-contained so it can be rendered without extra editing.\n"
        )

    @staticmethod
    def _build_schema(section_count: int) -> dict[str, Any]:
        """告诉模型：返回的 JSON 必须长什么样。"""

        section_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "heading",
                "hook",
                "paragraphs",
                "bullets",
                "takeaway",
                "image_prompt",
                "image_alt",
                "image_caption",
            ],
            "properties": {
                "heading": {"type": "string"},
                "hook": {"type": "string"},
                "paragraphs": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": {"type": "string"},
                },
                "bullets": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 5,
                    "items": {"type": "string"},
                },
                "takeaway": {"type": "string"},
                "image_prompt": {"type": "string"},
                "image_alt": {"type": "string"},
                "image_caption": {"type": "string"},
            },
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "title",
                "subtitle",
                "summary",
                "cover_image_prompt",
                "cover_image_alt",
                "intro_paragraphs",
                "sections",
                "conclusion_title",
                "conclusion_paragraphs",
                "call_to_action",
                "tags",
            ],
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "summary": {"type": "string"},
                "cover_image_prompt": {"type": "string"},
                "cover_image_alt": {"type": "string"},
                "intro_paragraphs": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"type": "string"},
                },
                "sections": {
                    "type": "array",
                    "minItems": section_count,
                    "maxItems": section_count,
                    "items": section_schema,
                },
                "conclusion_title": {"type": "string"},
                "conclusion_paragraphs": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"type": "string"},
                },
                "call_to_action": {"type": "string"},
                "tags": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 8,
                    "items": {"type": "string"},
                },
            },
        }


class UnifiedTextGenerationTool:
    """通过统一文本接口生成文章草稿，直连 xAI 仅作为兜底。"""

    def __init__(
        self,
        api_url: str,
        candidates: list[TextGatewayCandidate],
        timeout_seconds: int,
        retry_attempts: int,
        retry_backoff_seconds: float,
        prompt_profile: str,
        fallback_tool: XAITextGenerationTool | None = None,
    ):
        self.api_url = api_url
        self.candidates = candidates
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.prompt_profile = prompt_profile
        self.fallback_tool = fallback_tool

    def generate_article_draft(self, request: ArticleRequest) -> ArticleDraft:
        """并发竞速文本候选，谁先成功返回就用谁。"""

        tasks: list[tuple[str, Any]] = []
        for candidate in self.candidates:
            task_name = f"gateway:{candidate.provider}/{candidate.model}"
            tasks.append((task_name, lambda c=candidate: self._generate_via_gateway_candidate(c, request)))

        if self.fallback_tool is not None:
            tasks.append(("direct_xai", lambda: self._generate_via_direct_xai(request)))

        if not tasks:
            raise XAIAPIError("No text generation backend configured.")

        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            future_to_name = {executor.submit(task_fn): task_name for task_name, task_fn in tasks}
            for future in as_completed(future_to_name):
                task_name = future_to_name[future]
                try:
                    draft = future.result()
                    log_progress(f"Article draft winner: {task_name}")
                    return draft
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{task_name}:{exc}")
                    log_progress(f"Text candidate failed: {task_name}: {exc}")

        raise XAIAPIError("All text generation backends failed: " + " | ".join(errors[-10:]))

    def _generate_via_gateway_candidate(self, candidate: TextGatewayCandidate, request: ArticleRequest) -> ArticleDraft:
        prompt = self._build_gateway_prompt(request, self.prompt_profile)
        for attempt in range(1, self.retry_attempts + 1):
            log_progress(
                f"Generating article draft via text gateway {candidate.provider}/{candidate.model} "
                f"(attempt {attempt}/{self.retry_attempts})"
            )
            try:
                response = requests.post(
                    self.api_url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "prompt": prompt,
                    },
                    timeout=self.timeout_seconds,
                )
                data = _decode_json(response)
                if response.status_code >= 400:
                    if _is_retryable_http_status(response.status_code) and attempt < self.retry_attempts:
                        backoff_seconds = self.retry_backoff_seconds * attempt + random.uniform(0.2, 0.8)
                        log_progress(
                            f"Text gateway HTTP {response.status_code}, retrying after {backoff_seconds:.1f}s "
                            f"for {candidate.provider}/{candidate.model}"
                        )
                        time.sleep(backoff_seconds)
                        continue
                    raise XAIAPIError(_format_http_error(response.status_code, data))

                raw_text = data.get("text") if isinstance(data, dict) else None
                if not isinstance(raw_text, str) or not raw_text.strip():
                    raise XAIAPIError(f"Text gateway response missing text: {data}")
                article_data = json.loads(_strip_json_fences(raw_text))
                draft = ArticleDraft.from_dict(article_data, expected_sections=request.sections)
                log_progress(f"Article draft generated via text gateway: {candidate.provider}/{candidate.model}")
                return draft
            except Exception:
                if attempt >= self.retry_attempts:
                    raise
        raise XAIAPIError(f"Text gateway candidate exhausted retries: {candidate.provider}/{candidate.model}")

    def _generate_via_direct_xai(self, request: ArticleRequest) -> ArticleDraft:
        if self.fallback_tool is None:
            raise XAIAPIError("Direct xAI tool is not configured.")
        log_progress("Generating article draft via direct xAI API (race candidate)")
        return self.fallback_tool.generate_article_draft(request)

    @staticmethod
    def _build_gateway_prompt(request: ArticleRequest, prompt_profile: str) -> str:
        schema = XAITextGenerationTool._build_schema(request.sections)
        quality_hint = TEXT_PROMPT_PROFILE_HINTS.get(prompt_profile, TEXT_PROMPT_PROFILE_HINTS["balanced"])
        return (
            f"{XAITextGenerationTool._build_system_prompt()}\n\n"
            f"{XAITextGenerationTool._build_user_prompt(request)}\n\n"
            f"Generation profile: {prompt_profile}\n"
            f"Extra guidance: {quality_hint}\n"
            "Output safety rules:\n"
            "- Return ONLY one JSON object, no markdown fences, no preface.\n"
            "- Keep intro_paragraphs 1-2 items; conclusion_paragraphs 1-2 items.\n"
            "- Keep each section paragraphs at 2-3 and bullets at 3-5.\n"
            "- If uncertain, avoid fabricated statistics and named reports.\n\n"
            "Return exactly one valid JSON object. Do not wrap it in markdown fences. "
            "The JSON object must match this JSON Schema exactly:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )


class XAIImageGenerationTool:
    """负责“根据提示词生成图片”这一步。"""

    def __init__(
        self,
        client: XAIHttpClient,
        fallback_api_url: str = SCRIPT_IMAGE_FALLBACK_API_URL,
        fallback_candidates: list[ImageFallbackCandidate] | None = None,
        xai_fallback_models: list[str] | None = None,
        gateway_storage_backend: str = SCRIPT_IMAGE_GATEWAY_STORAGE_BACKEND,
        prompt_profile: str = "balanced",
    ):
        self.client = client
        self.fallback_api_url = fallback_api_url
        self.fallback_candidates = fallback_candidates or []
        self.xai_fallback_models = xai_fallback_models or []
        self.gateway_storage_backend = gateway_storage_backend
        self.prompt_profile = prompt_profile
        self.fallback_session = requests.Session()
        self.fallback_session.headers.update({"Content-Type": "application/json"})

    def generate_image(
        self,
        prompt: str,
        alt_text: str,
        caption: str,
        aspect_ratio: str,
        resolution: str,
        destination: Path,
    ) -> GeneratedImage:
        """调用生图接口并把图片下载到本地。"""

        log_progress(f"Generating image: {destination.name}")
        tuned_prompt = self._enhance_image_prompt(prompt, aspect_ratio, resolution)
        source_url: str | None = None
        revised_prompt: str | None = None
        errors: list[str] = []

        if self.fallback_candidates:
            source_url = self._generate_image_url_via_fallback_service(tuned_prompt, aspect_ratio, resolution, errors)

        xai_models = (
            [self.client.config.image_model] + [m for m in self.xai_fallback_models if m != self.client.config.image_model]
            if self.client.config.api_key
            else []
        )
        if not source_url:
            for model_id in xai_models:
                try:
                    source_url, revised_prompt = self._generate_image_url_via_xai(
                        model_id=model_id,
                        prompt=tuned_prompt,
                        aspect_ratio=aspect_ratio,
                        resolution=resolution,
                    )
                    if source_url:
                        break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"xai:{model_id}:{exc}")
                    log_progress(f"xAI image generation failed for model={model_id}: {exc}")

        if not source_url:
            raise XAIAPIError("All image generation backends failed: " + " | ".join(errors[-8:]))

        # 生图接口返回的是远程 URL，这里额外下载到本地，方便 markdown/html 直接引用。
        local_file = self.client.download_binary(source_url, destination)
        log_progress(f"Image ready: {destination.name}")
        return GeneratedImage(
            prompt=tuned_prompt,
            source_url=source_url,
            alt_text=alt_text,
            caption=caption,
            revised_prompt=revised_prompt,
            local_path=local_file.name if local_file.parent == destination.parent else str(local_file),
        )

    def _enhance_image_prompt(self, prompt: str, aspect_ratio: str, resolution: str) -> str:
        """把草稿里的图片描述增强为稳定可执行的生图提示词。"""

        base_prompt = " ".join(prompt.split())
        suffix = IMAGE_PROMPT_PROFILE_SUFFIX.get(self.prompt_profile, IMAGE_PROMPT_PROFILE_SUFFIX["balanced"])
        if "no text overlay" in base_prompt.lower():
            # 已经有关键约束时，避免重复太多。
            return f"{base_prompt}, aspect ratio {aspect_ratio}, resolution {resolution}, {suffix}"
        return (
            f"{base_prompt}, aspect ratio {aspect_ratio}, resolution {resolution}, "
            f"{suffix}, no text overlay"
        )

    def _generate_image_url_via_xai(
        self,
        model_id: str,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
    ) -> tuple[str, str | None]:
        payload = {
            "model": model_id,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        response = self.client.post_json("/images/generations", payload)
        image_data = extract_first_image_object(response)
        source_url = image_data.get("url")
        if not source_url:
            raise XAIAPIError(f"Image generation response did not include a URL: {image_data}")
        return source_url, image_data.get("revised_prompt")

    def _generate_image_url_via_fallback_service(
        self,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        errors: list[str],
    ) -> str | None:
        for candidate in self.fallback_candidates:
            for attempt in range(1, self.client.config.retry_attempts + 1):
                try:
                    payload: dict[str, Any] = {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "n": 1,
                        "prompt": prompt,
                        "storage_backend": self.gateway_storage_backend,
                    }
                    if candidate.provider == "grok":
                        payload["aspectRatio"] = aspect_ratio
                        payload["resolution"] = resolution
                    elif candidate.provider == "vertex":
                        payload["parameters"] = {"aspectRatio": _normalize_vertex_aspect_ratio(aspect_ratio)}

                    log_progress(
                        f"Image gateway generation via {candidate.provider}/{candidate.model} "
                        f"(attempt {attempt}/{self.client.config.retry_attempts})"
                    )
                    response = self.fallback_session.post(
                        self.fallback_api_url,
                        json=payload,
                        timeout=self.client.config.timeout_seconds,
                    )
                    data = _decode_json(response)
                    if response.status_code >= 400:
                        if _is_retryable_http_status(response.status_code) and attempt < self.client.config.retry_attempts:
                            backoff_seconds = self.client.config.retry_backoff_seconds * attempt + random.uniform(0.2, 0.8)
                            log_progress(
                                f"Fallback HTTP {response.status_code}, retrying after {backoff_seconds:.1f}s "
                                f"for {candidate.provider}/{candidate.model}"
                            )
                            time.sleep(backoff_seconds)
                            continue
                        raise XAIAPIError(_format_http_error(response.status_code, data))
                    image_urls = data.get("image_urls") if isinstance(data, dict) else None
                    if isinstance(image_urls, list) and image_urls and isinstance(image_urls[0], str):
                        return image_urls[0]
                    raise XAIAPIError(f"Fallback response missing image_urls: {data}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"fallback:{candidate.provider}:{candidate.model}:{exc}")
                    if attempt == self.client.config.retry_attempts:
                        log_progress(f"Fallback failed for {candidate.provider}/{candidate.model}: {exc}")
                        break
        return None


class WeChatArticleComposer:
    """总调度器：把“写文章”“生图片”“导出文件”串起来。"""

    def __init__(
        self,
        text_tool: XAITextGenerationTool,
        image_tool: XAIImageGenerationTool,
        oss_uploader: "OSSUploader | None" = None,
    ):
        self.text_tool = text_tool
        self.image_tool = image_tool
        self.oss_uploader = oss_uploader

    def compose(self, request: ArticleRequest, output_dir: Path) -> ArticleBundle:
        """生成整套文章包并写入输出目录。"""

        log_progress(f"Preparing output directory: {output_dir}")
        # 先准备输出目录结构。
        output_dir.mkdir(parents=True, exist_ok=True)
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # 第一步：先生成文字草稿。
        draft = self.text_tool.generate_article_draft(request)
        # 草稿先单独保存下来，这样即使后面的生图失败，你也能看到完整文章结构。
        log_progress("Saving draft files before image generation")
        self._write_draft_files(output_dir, request, draft)
        log_progress(f"Draft markdown saved: {output_dir / 'draft.md'}")
        log_progress(f"Draft json saved: {output_dir / 'draft.json'}")
        # 第二步：并发生成封面图 + 正文配图，提升吞吐并降低单次失败影响面。
        image_jobs: list[tuple[str, dict[str, Any]]] = [
            (
                "cover",
                {
                    "prompt": draft.cover_image_prompt,
                    "alt_text": draft.cover_image_alt,
                    "caption": draft.subtitle,
                    "aspect_ratio": request.aspect_ratio,
                    "resolution": request.resolution,
                    "destination": images_dir / "cover",
                },
            )
        ]
        for index, section in enumerate(draft.sections, start=1):
            image_jobs.append(
                (
                    f"section-{index:02d}",
                    {
                        "prompt": section.image_prompt,
                        "alt_text": section.image_alt,
                        "caption": section.image_caption,
                        "aspect_ratio": request.aspect_ratio,
                        "resolution": request.resolution,
                        "destination": images_dir / f"section-{index:02d}",
                    },
                )
            )

        max_workers = max(1, min(SCRIPT_IMAGE_MAX_CONCURRENCY, len(image_jobs)))
        log_progress(f"Generating {len(image_jobs)} images concurrently (workers={max_workers})")
        image_results: dict[str, GeneratedImage] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self.image_tool.generate_image, **job_kwargs): job_name
                for job_name, job_kwargs in image_jobs
            }
            for future in as_completed(future_map):
                job_name = future_map[future]
                image_results[job_name] = future.result()
                log_progress(f"Image generation completed: {job_name}")

        cover_image = image_results["cover"]
        section_images = [image_results[f"section-{index:02d}"] for index in range(1, len(draft.sections) + 1)]

        # 第四步：把最终内容分别渲染成 markdown 和 html。
        log_progress("Rendering markdown and html")
        markdown = render_markdown(draft, cover_image, section_images)
        html = render_html(draft, cover_image, section_images)

        # 第五步：把所有文件落盘。
        log_progress("Writing output files")
        public_urls = None
        self._write_bundle_files(output_dir, request, draft, cover_image, section_images, markdown, html)
        if self.oss_uploader is not None:
            log_progress("Uploading output files to OSS")
            public_urls = self.oss_uploader.upload_output_bundle(output_dir)
            self._rewrite_rendered_assets_for_public_urls(output_dir, public_urls)
            self._write_public_urls(output_dir, public_urls)
            # article.html / article.md / article.json rewritten after first upload,
            # so upload once more to keep OSS objects in sync with rewritten links.
            public_urls = self.oss_uploader.upload_output_bundle(output_dir)
            log_progress(f"OSS upload done: {public_urls['article_html']}")
        log_progress("All files written successfully")

        return ArticleBundle(
            request=request,
            draft=draft,
            cover_image=cover_image,
            section_images=section_images,
            markdown=markdown,
            html=html,
            output_dir=str(output_dir),
            public_urls=public_urls,
        )

    @staticmethod
    def _write_bundle_files(
        output_dir: Path,
        request: ArticleRequest,
        draft: ArticleDraft,
        cover_image: GeneratedImage,
        section_images: list[GeneratedImage],
        markdown: str,
        html: str,
    ) -> None:
        """把结果写成 article.md、article.html、article.json。"""

        (output_dir / "article.md").write_text(markdown, encoding="utf-8")
        (output_dir / "article.html").write_text(html, encoding="utf-8")
        manifest = {
            "request": asdict(request),
            "draft": asdict(draft),
            "cover_image": asdict(cover_image),
            "section_images": [asdict(image) for image in section_images],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        (output_dir / "article.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _write_draft_files(output_dir: Path, request: ArticleRequest, draft: ArticleDraft) -> None:
        """先把纯草稿保存下来，便于单独查看文本生成结果。"""

        draft_manifest = {
            "request": asdict(request),
            "draft": asdict(draft),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        (output_dir / "draft.json").write_text(
            json.dumps(draft_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "draft.md").write_text(render_draft_markdown(draft), encoding="utf-8")

    @staticmethod
    def _write_public_urls(output_dir: Path, public_urls: dict[str, str]) -> None:
        """把 OSS 公网链接写入 article.json，供服务端直接返回。"""

        manifest_path = output_dir / "article.json"
        if not manifest_path.exists():
            return
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["public_urls"] = public_urls
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _rewrite_rendered_assets_for_public_urls(output_dir: Path, public_urls: dict[str, str]) -> None:
        """将文章渲染结果里的本地图片路径替换为 OSS 公网地址。"""

        images_base_url = public_urls.get("images_base_url")
        if not images_base_url:
            return

        article_md_path = output_dir / "article.md"
        if article_md_path.exists():
            markdown = article_md_path.read_text(encoding="utf-8")
            markdown = markdown.replace("(images/", f"({images_base_url}")
            markdown = markdown.replace("](/images/", f"]({images_base_url}")
            article_md_path.write_text(markdown, encoding="utf-8")

        article_html_path = output_dir / "article.html"
        if article_html_path.exists():
            html = article_html_path.read_text(encoding="utf-8")
            html = html.replace('src="images/', f'src="{images_base_url}')
            html = html.replace("src='images/", f"src='{images_base_url}")
            article_html_path.write_text(html, encoding="utf-8")


class OSSUploader:
    """上传生成产物到阿里云 OSS，并返回可直接访问的链接。"""

    def __init__(self, config: OSSConfig):
        try:
            import oss2  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError("oss2 is required for OSS upload. Install with: pip install oss2") from exc
        self.oss2 = oss2
        self.config = config
        auth = self.oss2.Auth(config.access_key_id, config.access_key_secret)
        self.bucket = self.oss2.Bucket(auth, config.endpoint, config.bucket_name)

    def upload_output_bundle(self, output_dir: Path) -> dict[str, str]:
        """上传文章产物目录，返回关键文件公网链接。"""

        bundle_prefix = "/".join(
            [
                self.config.key_prefix.strip("/"),
                output_dir.name.strip("/"),
            ]
        ).strip("/")

        for file_path in sorted(output_dir.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(output_dir).as_posix()
            object_key = f"{bundle_prefix}/{relative}"
            self.bucket.put_object_from_file(object_key, str(file_path), headers=self._upload_headers(file_path))
            log_progress(f"OSS uploaded: {object_key}")

        return {
            "article_html": self._public_url(f"{bundle_prefix}/article.html"),
            "article_markdown": self._public_url(f"{bundle_prefix}/article.md"),
            "article_json": self._public_url(f"{bundle_prefix}/article.json"),
            "draft_markdown": self._public_url(f"{bundle_prefix}/draft.md"),
            "draft_json": self._public_url(f"{bundle_prefix}/draft.json"),
            "images_base_url": self._public_url(f"{bundle_prefix}/images/"),
            "output_dir": self._public_url(f"{bundle_prefix}/"),
        }

    def _public_url(self, object_key: str) -> str:
        if self.config.public_base_url:
            return f"{self.config.public_base_url.rstrip('/')}/{object_key.lstrip('/')}"
        endpoint = self.config.endpoint.strip()
        if endpoint.startswith("http://"):
            host = endpoint.removeprefix("http://")
            scheme = "http"
        elif endpoint.startswith("https://"):
            host = endpoint.removeprefix("https://")
            scheme = "https"
        else:
            host = endpoint
            scheme = "https"
        return f"{scheme}://{self.config.bucket_name}.{host.rstrip('/')}/{object_key.lstrip('/')}"

    @staticmethod
    def _upload_headers(file_path: Path) -> dict[str, str]:
        """为 OSS 对象设置可预览的元数据。"""

        suffix = file_path.suffix.lower()
        if suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif suffix in {".md", ".markdown"}:
            content_type = "text/markdown; charset=utf-8"
        elif suffix == ".json":
            content_type = "application/json; charset=utf-8"
        else:
            guessed = mimetypes.guess_type(file_path.name)[0]
            content_type = guessed or "application/octet-stream"
        headers = {"Content-Type": content_type}
        if suffix in {".html", ".md", ".markdown", ".json", ".txt"}:
            headers["Content-Disposition"] = "inline"
        return headers


def extract_response_output_text(response_payload: dict[str, Any]) -> str:
    """从 responses 接口返回体里提取真正的文本内容。"""

    for item in response_payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise XAIAPIError(f"Responses payload did not contain output_text: {response_payload}")


def extract_first_image_object(response_payload: dict[str, Any]) -> dict[str, Any]:
    """从图片接口返回体里取第一张图的信息。"""

    data = response_payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
    raise XAIAPIError(f"Image payload did not contain generated images: {response_payload}")


def render_markdown(draft: ArticleDraft, cover_image: GeneratedImage, section_images: list[GeneratedImage]) -> str:
    """把文章对象渲染成 markdown，方便你在编辑器里直接看。"""

    cover_ref = _asset_reference("images", cover_image.local_path, cover_image.source_url)
    lines = [
        f"# {draft.title}",
        "",
        f"> {draft.subtitle}",
        "",
        f"![{cover_image.alt_text}]({cover_ref})",
        "",
        f"*{draft.summary}*",
        "",
    ]

    for paragraph in draft.intro_paragraphs:
        lines.extend([paragraph, ""])

    for index, section in enumerate(draft.sections):
        section_image = section_images[index]
        section_ref = _asset_reference("images", section_image.local_path, section_image.source_url)
        lines.extend(
            [
                f"## {index + 1}. {section.heading}",
                "",
                f"**{section.hook}**",
                "",
            ]
        )
        for paragraph in section.paragraphs:
            lines.extend([paragraph, ""])
        for bullet in section.bullets:
            lines.append(f"- {bullet}")
        lines.extend(
            [
                "",
                f"![{section_image.alt_text}]({section_ref})",
                "",
                f"> {section_image.caption}",
                "",
                f"**Section takeaway:** {section.takeaway}",
                "",
            ]
        )

    lines.extend([f"## {draft.conclusion_title}", ""])
    for paragraph in draft.conclusion_paragraphs:
        lines.extend([paragraph, ""])
    lines.extend(
        [
            f"**CTA:** {draft.call_to_action}",
            "",
            "Tags: " + " / ".join(draft.tags),
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def render_draft_markdown(draft: ArticleDraft) -> str:
    """把“纯文章草稿”渲染成 markdown，方便先看文字结构。"""

    lines = [
        f"# {draft.title}",
        "",
        f"> {draft.subtitle}",
        "",
        "## 摘要",
        "",
        draft.summary,
        "",
        "## 封面图设定",
        "",
        f"- 封面图 alt: {draft.cover_image_alt}",
        f"- 封面图 prompt: {draft.cover_image_prompt}",
        "",
        "## 导语",
        "",
    ]
    for paragraph in draft.intro_paragraphs:
        lines.extend([paragraph, ""])

    for index, section in enumerate(draft.sections, start=1):
        lines.extend(
            [
                f"## {index}. {section.heading}",
                "",
                f"**Hook:** {section.hook}",
                "",
            ]
        )
        for paragraph in section.paragraphs:
            lines.extend([paragraph, ""])
        for bullet in section.bullets:
            lines.append(f"- {bullet}")
        lines.extend(
            [
                "",
                f"**Section takeaway:** {section.takeaway}",
                "",
                f"**Image prompt:** {section.image_prompt}",
                "",
                f"**Image alt:** {section.image_alt}",
                "",
                f"**Image caption:** {section.image_caption}",
                "",
            ]
        )

    lines.extend([f"## {draft.conclusion_title}", ""])
    for paragraph in draft.conclusion_paragraphs:
        lines.extend([paragraph, ""])
    lines.extend(
        [
            f"**CTA:** {draft.call_to_action}",
            "",
            "Tags: " + " / ".join(draft.tags),
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def render_html(draft: ArticleDraft, cover_image: GeneratedImage, section_images: list[GeneratedImage]) -> str:
    """把文章对象渲染成可直接打开的独立 HTML 页面。"""

    cover_ref = _asset_reference("images", cover_image.local_path, cover_image.source_url)
    parts = [
        "<!DOCTYPE html>",
        "<html lang=\"zh-CN\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{escape(draft.title)}</title>",
        # 这里直接把样式写进 HTML，目的是让生成结果不依赖外部 CSS 文件。
        "<style>",
        ":root { color-scheme: light; --bg: #f6f1e8; --ink: #1b1a17; --muted: #645f56; --card: #fffaf3; --accent: #a8572b; }",
        "body { margin: 0; font-family: 'Noto Serif SC', 'Microsoft YaHei', serif; background: radial-gradient(circle at top, #fffaf0 0%, var(--bg) 55%, #efe4d2 100%); color: var(--ink); }",
        ".shell { max-width: 860px; margin: 0 auto; padding: 32px 18px 72px; }",
        ".hero, .section, .closing { background: rgba(255, 250, 243, 0.94); border: 1px solid rgba(27, 26, 23, 0.08); border-radius: 24px; box-shadow: 0 18px 60px rgba(46, 35, 20, 0.08); padding: 24px; margin-bottom: 22px; }",
        "h1, h2 { margin: 0; line-height: 1.2; }",
        "h1 { font-size: clamp(2rem, 5vw, 3.5rem); }",
        ".subtitle { margin-top: 14px; font-size: 1.05rem; color: var(--muted); }",
        ".summary { margin-top: 20px; padding: 14px 18px; border-left: 4px solid var(--accent); background: rgba(168, 87, 43, 0.08); }",
        "figure { margin: 22px 0 0; }",
        "img { width: 100%; border-radius: 18px; display: block; object-fit: cover; }",
        "figcaption { margin-top: 10px; font-size: 0.92rem; color: var(--muted); }",
        ".hook { font-weight: 700; color: var(--accent); margin-top: 14px; }",
        "p { font-size: 1.02rem; line-height: 1.9; margin: 14px 0 0; }",
        "ul { margin: 16px 0 0 20px; padding: 0; }",
        "li { margin-top: 8px; line-height: 1.8; }",
        ".takeaway { margin-top: 18px; font-weight: 700; }",
        ".tags { margin-top: 20px; display: flex; flex-wrap: wrap; gap: 10px; }",
        ".tag { border-radius: 999px; padding: 8px 12px; background: rgba(168, 87, 43, 0.1); color: var(--accent); font-size: 0.92rem; }",
        "@media (max-width: 640px) { .hero, .section, .closing { padding: 20px; border-radius: 20px; } }",
        "</style>",
        "</head>",
        "<body>",
        "<main class=\"shell\">",
        "<article class=\"hero\">",
        f"<h1>{escape(draft.title)}</h1>",
        f"<p class=\"subtitle\">{escape(draft.subtitle)}</p>",
        f"<div class=\"summary\">{escape(draft.summary)}</div>",
    ]

    for paragraph in draft.intro_paragraphs:
        parts.append(f"<p>{escape(paragraph)}</p>")

    parts.extend(
        [
            "<figure>",
            f"<img src=\"{escape(cover_ref)}\" alt=\"{escape(cover_image.alt_text)}\">",
            f"<figcaption>{escape(cover_image.caption)}</figcaption>",
            "</figure>",
            "</article>",
        ]
    )

    for index, section in enumerate(draft.sections):
        section_image = section_images[index]
        section_ref = _asset_reference("images", section_image.local_path, section_image.source_url)
        parts.extend(
            [
                "<section class=\"section\">",
                f"<h2>{index + 1}. {escape(section.heading)}</h2>",
                f"<p class=\"hook\">{escape(section.hook)}</p>",
            ]
        )
        for paragraph in section.paragraphs:
            parts.append(f"<p>{escape(paragraph)}</p>")
        parts.append("<ul>")
        for bullet in section.bullets:
            parts.append(f"<li>{escape(bullet)}</li>")
        parts.extend(
            [
                "</ul>",
                "<figure>",
                f"<img src=\"{escape(section_ref)}\" alt=\"{escape(section_image.alt_text)}\">",
                f"<figcaption>{escape(section_image.caption)}</figcaption>",
                "</figure>",
                f"<p class=\"takeaway\">Section takeaway: {escape(section.takeaway)}</p>",
                "</section>",
            ]
        )

    parts.extend([f"<section class=\"closing\"><h2>{escape(draft.conclusion_title)}</h2>"])
    for paragraph in draft.conclusion_paragraphs:
        parts.append(f"<p>{escape(paragraph)}</p>")
    parts.extend(
        [
            f"<p class=\"takeaway\">CTA: {escape(draft.call_to_action)}</p>",
            "<div class=\"tags\">",
        ]
    )
    for tag in draft.tags:
        parts.append(f"<span class=\"tag\">{escape(tag)}</span>")
    parts.extend(["</div>", "</section>", "</main>", "</body>", "</html>"])
    return "\n".join(parts)


def build_default_output_dir(topic: str) -> Path:
    """根据主题和当前时间，自动生成一个新的输出目录名。"""

    slug = slugify(topic)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("examples") / "generated_articles" / f"{slug}-{timestamp}"


def slugify(text: str) -> str:
    """把主题转成相对安全的目录名。"""

    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "wechat-article"


def _asset_reference(folder_name: str, local_path: str | None, fallback_url: str) -> str:
    """决定 markdown/html 里应该引用本地路径还是远程 URL。"""

    if not local_path:
        return fallback_url
    local = Path(local_path)
    if local.parent.name == folder_name:
        return local.as_posix()
    if len(local.parts) == 1:
        return f"{folder_name}/{local.name}"
    return local.as_posix()


def _require_string(payload: dict[str, Any], key: str) -> str:
    """校验某个字段必须是非空字符串。"""

    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string for '{key}', got {value!r}")
    return value.strip()


def _require_list(payload: dict[str, Any], key: str, min_items: int) -> list[Any]:
    """校验某个字段必须是列表，且至少有指定数量的元素。"""

    value = payload.get(key)
    if not isinstance(value, list) or len(value) < min_items:
        raise ValueError(f"Expected list for '{key}' with at least {min_items} items, got {value!r}")
    return value


def _require_list_of_strings(payload: dict[str, Any], key: str, min_items: int) -> list[str]:
    """校验某个字段必须是“非空字符串列表”。"""

    items = _require_list(payload, key, min_items=min_items)
    cleaned: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Expected non-empty string items for '{key}', got {items!r}")
        cleaned.append(item.strip())
    return cleaned


def _decode_json(response: requests.Response) -> dict[str, Any]:
    """把 HTTP 响应解码成 JSON；失败时给出更明确的错误。"""

    try:
        return response.json()
    except ValueError as exc:
        raise XAIAPIError(f"Expected JSON response, got: {response.text[:500]}") from exc


def _format_http_error(status_code: int, payload: dict[str, Any]) -> str:
    """把 HTTP 状态码和返回体拼成更易读的报错信息。"""

    message = payload.get("error") if isinstance(payload, dict) else payload
    return f"xAI API request failed with status {status_code}: {message}"


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code in {429, 500, 502, 503, 504}


def _strip_json_fences(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _normalize_vertex_aspect_ratio(aspect_ratio: str) -> str:
    allowed = {"1:1", "3:4", "4:3", "9:16", "16:9"}
    return aspect_ratio if aspect_ratio in allowed else "16:9"


def _guess_image_extension(url: str, content_type: str) -> str:
    """根据 Content-Type 或 URL 猜测图片后缀名。"""

    content_type = content_type.split(";", 1)[0].strip().lower()
    by_type = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    if content_type in by_type:
        return by_type[content_type]

    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix or ".jpg"


def load_creative_presets(preset_file: Path) -> list[CreativePreset]:
    """从 json 文件里加载全部创意预设。"""

    if not preset_file.exists():
        raise FileNotFoundError(f"Creative preset file not found: {preset_file}")

    payload = json.loads(preset_file.read_text(encoding="utf-8"))
    presets_payload = payload.get("presets") if isinstance(payload, dict) else payload
    if not isinstance(presets_payload, list) or not presets_payload:
        raise ValueError(f"Creative preset file must contain a non-empty preset list: {preset_file}")

    presets: list[CreativePreset] = []
    for item in presets_payload:
        if not isinstance(item, dict):
            raise ValueError(f"Creative preset entries must be objects: {item!r}")
        presets.append(CreativePreset.from_dict(item))
    return presets


def select_creative_preset(presets: list[CreativePreset], preset_index: int) -> CreativePreset:
    """按 1-based 序号选出一套创意预设。"""

    if preset_index < 1 or preset_index > len(presets):
        raise ValueError(f"Preset index must be between 1 and {len(presets)}, got {preset_index}.")
    return presets[preset_index - 1]


def resolve_selected_creative_preset() -> CreativePreset:
    """读取预设文件并返回当前选中的那一套。"""

    return select_creative_preset(load_creative_presets(Path(SCRIPT_PRESET_FILE)), SCRIPT_PRESET_INDEX)


def log_progress(message: str) -> None:
    """打印进度日志，并立即刷新到控制台。"""

    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """保留的命令行解析函数。

    当前主流程已经不依赖命令行参数了，但这个函数还在，方便以后需要时复用。
    """

    preset = resolve_selected_creative_preset()
    request = preset.to_article_request()
    parser = argparse.ArgumentParser(description="Generate a Grok-powered WeChat article with images.")
    parser.add_argument("--topic", default=request.topic, help="Main topic of the article.")
    parser.add_argument("--audience", default=request.audience, help="Target audience description.")
    parser.add_argument("--tone", default=request.tone, help="Editorial tone.")
    parser.add_argument("--sections", type=int, default=request.sections, help="Number of main sections.")
    parser.add_argument(
        "--use-web-search",
        action=argparse.BooleanOptionalAction,
        default=request.use_web_search,
        help="Allow Grok to use xAI web search for current facts.",
    )
    parser.add_argument("--image-style", default=request.image_style, help="Illustration style guidance for all images.")
    parser.add_argument("--aspect-ratio", default=request.aspect_ratio, help="Image aspect ratio, e.g. 16:9.")
    parser.add_argument("--resolution", default=request.resolution, help="Image resolution, e.g. 1k or 2k.")
    parser.add_argument(
        "--storage-mode",
        default=SCRIPT_STORAGE_MODE,
        choices=["local", "remote"],
        help="Artifact storage mode: local (no OSS) or remote (upload to OSS and rewrite links).",
    )
    parser.add_argument(
        "--api-key",
        default=SCRIPT_API_KEY or resolve_api_key(),
        help="xAI API key. Defaults to GROPK_API_KEY, GROK_API_KEY, or XAI_API_KEY.",
    )
    parser.add_argument("--base-url", default=os.getenv("XAI_BASE_URL", SCRIPT_BASE_URL), help="xAI API base URL.")
    parser.add_argument("--text-model", default=os.getenv("XAI_TEXT_MODEL", SCRIPT_TEXT_MODEL), help="xAI text model.")
    parser.add_argument(
        "--image-model",
        default=os.getenv("XAI_IMAGE_MODEL", SCRIPT_IMAGE_MODEL),
        help="xAI image model.",
    )
    parser.add_argument("--output-dir", default=SCRIPT_OUTPUT_DIR, help="Directory where article assets will be written.")
    return parser.parse_args(argv)


def generate_wechat_article(
    preset_index: int = SCRIPT_PRESET_INDEX,
    output_dir: Path | None = None,
    topic: str | None = None,
    audience: str | None = None,
    tone: str | None = None,
    sections: int | None = None,
    use_web_search: bool | None = None,
    image_style: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    storage_mode: str | None = None,
    generation_profile: str | None = None,
) -> ArticleBundle:
    """Generate a complete WeChat article bundle.

    This is the reusable entry point for both the command-line script and the HTTP service.
    """

    load_project_dotenv()

    preset = select_creative_preset(load_creative_presets(Path(SCRIPT_PRESET_FILE)), preset_index)
    request = preset.to_article_request()
    selected_topic = topic if topic is not None else request.topic
    selected_topic = selected_topic.strip() if isinstance(selected_topic, str) else ""
    request = ArticleRequest(
        topic=selected_topic,
        audience=audience if audience is not None else request.audience,
        tone=tone if tone is not None else request.tone,
        sections=sections if sections is not None else request.sections,
        use_web_search=use_web_search if use_web_search is not None else request.use_web_search,
        image_style=image_style if image_style is not None else request.image_style,
        aspect_ratio=aspect_ratio if aspect_ratio is not None else request.aspect_ratio,
        resolution=resolution if resolution is not None else request.resolution,
    )
    api_key = SCRIPT_API_KEY or resolve_api_key()
    base_url = os.getenv("XAI_BASE_URL", SCRIPT_BASE_URL)
    text_model = os.getenv("XAI_TEXT_MODEL", SCRIPT_TEXT_MODEL)
    image_model = os.getenv("XAI_IMAGE_MODEL", SCRIPT_IMAGE_MODEL)
    output_dir_value = output_dir or (Path(SCRIPT_OUTPUT_DIR) if SCRIPT_OUTPUT_DIR else None)
    selected_storage_mode = (storage_mode or SCRIPT_STORAGE_MODE).strip().lower()
    selected_generation_profile = (generation_profile or SCRIPT_GENERATION_PROFILE).strip().lower()

    # 启动时先打印关键配置，方便排查“到底连的是谁、Key 有没有读到”。
    log_progress(f"Using xAI base URL: {base_url.rstrip('/')}")
    log_progress(f"API key loaded: {'yes' if bool(api_key) else 'no'}")
    log_progress(f"Using creative preset #{preset_index}: {preset.name}")
    log_progress(f"Preset topic: {request.topic}")
    log_progress(
        "Network config: "
        f"timeout={SCRIPT_TIMEOUT_SECONDS}s, retries={SCRIPT_RETRY_ATTEMPTS}, "
        f"backoff={SCRIPT_RETRY_BACKOFF_SECONDS}s"
    )

    # 先做最基本的输入校验，尽量在真正调用接口前就发现问题。
    if not selected_topic:
        raise SystemExit("Missing topic in selected preset. Update the preset json file.")
    if request.sections < 1:
        raise SystemExit("Preset section_count must be at least 1.")
    if selected_storage_mode not in {"local", "remote"}:
        raise SystemExit("storage_mode must be either 'local' or 'remote'.")
    if selected_generation_profile not in SCRIPT_GENERATION_PROFILES:
        supported_profiles = ", ".join(sorted(SCRIPT_GENERATION_PROFILES))
        raise SystemExit(f"generation_profile must be one of: {supported_profiles}.")
    # 如果你没有手写输出目录，就自动按主题创建一个新目录。
    target_output_dir = Path(output_dir_value) if output_dir_value else build_default_output_dir(selected_topic)

    # XAIConfig 是“模型调用配置”；后面的网络请求会用它。
    config = XAIConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        text_model=text_model,
        image_model=image_model,
        timeout_seconds=SCRIPT_TIMEOUT_SECONDS,
        retry_attempts=SCRIPT_RETRY_ATTEMPTS,
        retry_backoff_seconds=SCRIPT_RETRY_BACKOFF_SECONDS,
    )
    client = XAIHttpClient(config)
    direct_xai_text_tool = (
        XAITextGenerationTool(client) if api_key and SCRIPT_TEXT_ENABLE_DIRECT_XAI_FALLBACK else None
    )
    if not api_key:
        log_progress("xAI API key missing: direct xAI fallback is disabled, unified gateway remains enabled")
    elif not SCRIPT_TEXT_ENABLE_DIRECT_XAI_FALLBACK:
        log_progress("Direct xAI text fallback disabled: use unified text gateway candidates only")
    oss_uploader = None
    if selected_storage_mode == "remote":
        oss_config = resolve_oss_config()
        if oss_config is None:
            raise SystemExit(
                "storage_mode=remote requires OSS config. Set OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_BUCKET_NAME."
            )
        oss_uploader = OSSUploader(oss_config)
        log_progress(f"Storage mode: remote (OSS bucket={oss_config.bucket_name}, endpoint={oss_config.endpoint})")
    else:
        log_progress("Storage mode: local (skip OSS upload and URL rewrite)")
    profile = SCRIPT_GENERATION_PROFILES[selected_generation_profile]
    selected_prompt_profile = SCRIPT_PROMPT_PROFILE or selected_generation_profile
    text_candidates = resolve_text_gateway_candidates(profile["text_candidates"])
    image_candidates = resolve_image_fallback_candidates(profile["image_candidates"])
    log_progress(
        f"Generation profile: {selected_generation_profile} "
        f"(text={','.join(f'{item.provider}:{item.model}' for item in text_candidates)}; "
        f"image={','.join(f'{item.provider}:{item.model}' for item in image_candidates)})"
    )
    log_progress(f"Prompt profile: {selected_prompt_profile}")
    composer = WeChatArticleComposer(
        text_tool=UnifiedTextGenerationTool(
            api_url=SCRIPT_TEXT_GATEWAY_API_URL,
            candidates=text_candidates,
            timeout_seconds=SCRIPT_TEXT_GATEWAY_TIMEOUT_SECONDS,
            retry_attempts=SCRIPT_TEXT_GATEWAY_RETRY_ATTEMPTS,
            retry_backoff_seconds=SCRIPT_TEXT_GATEWAY_RETRY_BACKOFF_SECONDS,
            prompt_profile=selected_prompt_profile,
            fallback_tool=direct_xai_text_tool,
        ),
        image_tool=XAIImageGenerationTool(
            client,
            fallback_api_url=SCRIPT_IMAGE_FALLBACK_API_URL,
            fallback_candidates=image_candidates,
            xai_fallback_models=SCRIPT_IMAGE_FALLBACK_MODELS if api_key else [],
            gateway_storage_backend=SCRIPT_IMAGE_GATEWAY_STORAGE_BACKEND,
            prompt_profile=selected_prompt_profile,
        ),
        oss_uploader=oss_uploader,
    )
    # 这里开始真正生成文章、图片和输出文件。
    return composer.compose(request, output_dir=target_output_dir)


def main() -> None:
    """程序入口。

    主流程很简单：
    1. 读取你在顶部写好的配置。
    2. 组装成 ArticleRequest 和 XAIConfig。
    3. 调用总调度器生成整套文章。
    4. 打印输出文件位置。
    """

    bundle = generate_wechat_article()

    # 最后把关键输出路径打印出来，方便你马上打开结果。
    log_progress(f"Generated article title: {bundle.draft.title}")
    log_progress(f"Output directory: {bundle.output_dir}")
    log_progress(f"Markdown file: {Path(bundle.output_dir) / 'article.md'}")
    log_progress(f"HTML file: {Path(bundle.output_dir) / 'article.html'}")


def resolve_api_key() -> str | None:
    """按常见环境变量名称依次查找 API Key。"""

    for env_name in ("GROPK_API_KEY", "GROK_API_KEY", "XAI_API_KEY"):
        value = os.getenv(env_name)
        if value:
            return value
    return None


def load_project_dotenv() -> None:
    """加载项目根目录的 .env（如果存在），用于读取 XAI_API_KEY 等配置。"""

    if load_dotenv is not None and DEFAULT_DOTENV_PATH.exists():
        load_dotenv(dotenv_path=DEFAULT_DOTENV_PATH, override=False)
        return
    if load_dotenv is not None:
        # 兜底：如果用户从项目根目录运行，也能加载到 .env
        load_dotenv(override=False)
        return

    if not DEFAULT_DOTENV_PATH.exists():
        return

    for raw_line in DEFAULT_DOTENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("\"'")


def resolve_oss_config() -> OSSConfig | None:
    """从环境变量解析 OSS 配置，缺项时返回 None。"""

    access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
    access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
    bucket_name = os.getenv("OSS_BUCKET_NAME") or os.getenv("OSS_BUICTET") or DEFAULT_OSS_BUCKET
    endpoint = os.getenv("OSS_ENDPOINT", DEFAULT_OSS_ENDPOINT)
    key_prefix = os.getenv("OSS_KEY_PREFIX", "generated_articles")
    public_base_url = os.getenv("OSS_PUBLIC_BASE_URL")
    if not access_key_id or not access_key_secret or not bucket_name:
        return None
    return OSSConfig(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        bucket_name=bucket_name,
        endpoint=endpoint,
        key_prefix=key_prefix,
        public_base_url=public_base_url,
    )


def resolve_image_fallback_candidates(raw_candidates: list[str] | None = None) -> list[ImageFallbackCandidate]:
    """解析生图兜底候选列表。"""

    candidates: list[ImageFallbackCandidate] = []
    source = raw_candidates if raw_candidates is not None else SCRIPT_IMAGE_FALLBACK_CANDIDATES
    for raw in source:
        if ":" not in raw:
            continue
        provider, model = raw.split(":", 1)
        provider = provider.strip().lower()
        model = model.strip()
        if not provider or not model:
            continue
        candidates.append(ImageFallbackCandidate(provider=provider, model=model))
    return candidates


def resolve_text_gateway_candidates(raw_candidates: list[str] | None = None) -> list[TextGatewayCandidate]:
    """解析统一文本接口候选列表。"""

    candidates: list[TextGatewayCandidate] = []
    source = raw_candidates if raw_candidates is not None else SCRIPT_TEXT_GATEWAY_CANDIDATES
    for raw in source:
        if ":" not in raw:
            continue
        provider, model = raw.split(":", 1)
        provider = provider.strip().lower()
        model = model.strip()
        if not provider or not model:
            continue
        candidates.append(TextGatewayCandidate(provider=provider, model=model))
    return candidates


if __name__ == "__main__":
    main()
