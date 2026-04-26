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
import json
import os
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


class XAIImageGenerationTool:
    """负责“根据提示词生成图片”这一步。"""

    def __init__(self, client: XAIHttpClient):
        self.client = client

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
        payload = {
            "model": self.client.config.image_model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        response = self.client.post_json("/images/generations", payload)
        image_data = extract_first_image_object(response)
        source_url = image_data.get("url")
        if not source_url:
            raise XAIAPIError(f"Image generation response did not include a URL: {image_data}")

        # 生图接口返回的是远程 URL，这里额外下载到本地，方便 markdown/html 直接引用。
        local_file = self.client.download_binary(source_url, destination)
        log_progress(f"Image ready: {destination.name}")
        return GeneratedImage(
            prompt=prompt,
            source_url=source_url,
            alt_text=alt_text,
            caption=caption,
            revised_prompt=image_data.get("revised_prompt"),
            local_path=local_file.name if local_file.parent == destination.parent else str(local_file),
        )


class WeChatArticleComposer:
    """总调度器：把“写文章”“生图片”“导出文件”串起来。"""

    def __init__(self, text_tool: XAITextGenerationTool, image_tool: XAIImageGenerationTool):
        self.text_tool = text_tool
        self.image_tool = image_tool

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
        # 第二步：为封面图生成图片。
        log_progress("Generating cover image")
        cover_image = self.image_tool.generate_image(
            prompt=draft.cover_image_prompt,
            alt_text=draft.cover_image_alt,
            caption=draft.subtitle,
            aspect_ratio=request.aspect_ratio,
            resolution=request.resolution,
            destination=images_dir / "cover",
        )

        # 第三步：为每个正文小节各生成一张配图。
        section_images: list[GeneratedImage] = []
        for index, section in enumerate(draft.sections, start=1):
            log_progress(f"Generating section image {index}/{len(draft.sections)}")
            section_images.append(
                self.image_tool.generate_image(
                    prompt=section.image_prompt,
                    alt_text=section.image_alt,
                    caption=section.image_caption,
                    aspect_ratio=request.aspect_ratio,
                    resolution=request.resolution,
                    destination=images_dir / f"section-{index:02d}",
                )
            )

        # 第四步：把最终内容分别渲染成 markdown 和 html。
        log_progress("Rendering markdown and html")
        markdown = render_markdown(draft, cover_image, section_images)
        html = render_html(draft, cover_image, section_images)

        # 第五步：把所有文件落盘。
        log_progress("Writing output files")
        self._write_bundle_files(output_dir, request, draft, cover_image, section_images, markdown, html)
        log_progress("All files written successfully")

        return ArticleBundle(
            request=request,
            draft=draft,
            cover_image=cover_image,
            section_images=section_images,
            markdown=markdown,
            html=html,
            output_dir=str(output_dir),
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
    if not api_key:
        raise SystemExit("Missing xAI API key. Set XAI_API_KEY or pass --api-key.")
    if request.sections < 1:
        raise SystemExit("Preset section_count must be at least 1.")
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
    composer = WeChatArticleComposer(
        text_tool=XAITextGenerationTool(client),
        image_tool=XAIImageGenerationTool(client),
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


if __name__ == "__main__":
    main()
