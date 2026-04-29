from __future__ import annotations


"""HTTP console for the Grok WeChat article generator.

Run:
    .venv/bin/python examples/grok_wechat_server.py

Then open:
    http://127.0.0.1:8765
"""

import json
import mimetypes
import os
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import grok_wechat_article as generator


HOST = os.getenv("GROK_WECHAT_HOST", "127.0.0.1")
PORT = int(os.getenv("GROK_WECHAT_PORT", "8765"))
CORS_ALLOW_ORIGIN = os.getenv("GROK_WECHAT_CORS_ALLOW_ORIGIN", "*")
CORS_ALLOW_METHODS = os.getenv("GROK_WECHAT_CORS_ALLOW_METHODS", "GET, POST, HEAD, OPTIONS")
CORS_ALLOW_HEADERS = os.getenv("GROK_WECHAT_CORS_ALLOW_HEADERS", "Content-Type, X-API-Key, Authorization")
CORS_MAX_AGE = os.getenv("GROK_WECHAT_CORS_MAX_AGE", "86400")
API_IO_LOG_ENABLED = os.getenv("GROK_WECHAT_API_IO_LOG", "true").lower() in {"1", "true", "yes", "on"}
API_IO_LOG_MAX_CHARS = int(os.getenv("GROK_WECHAT_API_IO_LOG_MAX_CHARS", "4000"))
OUTPUT_ROOT = generator.PROJECT_ROOT / "examples" / "generated_articles"
JOB_STATE_DIR = OUTPUT_ROOT / "_jobs"
MAX_LOG_LINES = 200
GENERATION_LOCK = threading.Lock()
JOB_STATE_LOCK = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def create_job_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"article-{timestamp}-{uuid.uuid4().hex[:8]}"


def job_path(job_id: str) -> Path:
    return JOB_STATE_DIR / f"{job_id}.json"


def output_dir_for_job(job_id: str) -> Path:
    return OUTPUT_ROOT / job_id


def load_job(job_id: str) -> dict[str, Any] | None:
    path = job_path(job_id)
    if not path.exists():
        return None
    last_error: Exception | None = None
    # Under heavy concurrent logging, readers can hit a file mid-write.
    for _ in range(3):
        try:
            with JOB_STATE_LOCK:
                return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.02)
    raise ValueError(f"Failed to read job state for {job_id}: {last_error}") from last_error


def save_job(job: dict[str, Any]) -> None:
    JOB_STATE_DIR.mkdir(parents=True, exist_ok=True)
    target = job_path(job["job_id"])
    temp = target.with_suffix(".json.tmp")
    payload = json.dumps(job, ensure_ascii=False, indent=2)
    with JOB_STATE_LOCK:
        temp.write_text(payload, encoding="utf-8")
        temp.replace(target)


def append_log(job: dict[str, Any], message: str) -> None:
    logs = job.setdefault("logs", [])
    logs.append({"at": utc_now(), "message": message})
    if len(logs) > MAX_LOG_LINES:
        del logs[:-MAX_LOG_LINES]
    save_job(job)


def public_result_paths(job_id: str) -> dict[str, str]:
    return {
        "article_html": f"/outputs/{job_id}/article.html",
        "article_markdown": f"/outputs/{job_id}/article.md",
        "article_json": f"/outputs/{job_id}/article.json",
        "draft_markdown": f"/outputs/{job_id}/draft.md",
        "draft_json": f"/outputs/{job_id}/draft.json",
        "output_dir": str(output_dir_for_job(job_id)),
    }


def resolve_result_links(job_id: str, output_dir: Path | None = None) -> dict[str, str]:
    """优先返回 article.json 里持久化的公网链接。"""

    target_output_dir = output_dir or output_dir_for_job(job_id)
    article_json = target_output_dir / "article.json"
    if article_json.exists():
        try:
            payload = json.loads(article_json.read_text(encoding="utf-8"))
            public_urls = payload.get("public_urls")
            if isinstance(public_urls, dict) and all(isinstance(v, str) for v in public_urls.values()):
                fallback = public_result_paths(job_id)
                return {
                    "article_html": public_urls.get("article_html", fallback["article_html"]),
                    "article_markdown": public_urls.get("article_markdown", fallback["article_markdown"]),
                    "article_json": public_urls.get("article_json", fallback["article_json"]),
                    "draft_markdown": public_urls.get("draft_markdown", fallback["draft_markdown"]),
                    "draft_json": public_urls.get("draft_json", fallback["draft_json"]),
                    "output_dir": public_urls.get("output_dir", fallback["output_dir"]),
                }
        except (json.JSONDecodeError, OSError):
            pass
    return public_result_paths(job_id)


def require_api_key(handler: BaseHTTPRequestHandler) -> bool:
    expected = os.getenv("GROK_WECHAT_API_KEY")
    if not expected:
        return True
    provided = handler.headers.get("X-API-Key", "")
    if provided == expected:
        return True
    write_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "Missing or invalid X-API-Key header."})
    return False


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


def read_presets() -> list[dict[str, Any]]:
    presets = generator.load_creative_presets(Path(generator.SCRIPT_PRESET_FILE))
    return [{"index": index, **asdict(preset)} for index, preset in enumerate(presets, start=1)]


def read_raw_presets() -> dict[str, Any]:
    preset_file = Path(generator.SCRIPT_PRESET_FILE)
    return json.loads(preset_file.read_text(encoding="utf-8"))


def normalize_preset_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "preset" in payload:
        preset = payload["preset"]
        if not isinstance(preset, dict):
            raise ValueError("preset must be a JSON object.")
        merged = {**preset, **{key: value for key, value in payload.items() if key != "preset"}}
        payload = merged

    normalized = dict(payload)
    if "section_count" in normalized and "sections" not in normalized:
        normalized["sections"] = normalized["section_count"]
    return normalized


def coerce_article_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_preset_payload(payload)
    preset_index = int(payload.get("preset_index", generator.SCRIPT_PRESET_INDEX))
    presets = read_presets()
    if preset_index < 1 or preset_index > len(presets):
        raise ValueError(f"preset_index must be between 1 and {len(presets)}.")

    allowed_optional_fields = {
        "topic": str,
        "audience": str,
        "tone": str,
        "sections": int,
        "use_web_search": bool,
        "image_style": str,
        "aspect_ratio": str,
        "resolution": str,
        "storage_mode": str,
        "generation_profile": str,
        "outline": str,
        "story_type": str,
        "reference_image_url": str,  # 参考图片 URL，用于保持人物/场景一致性
        "reference_character_profile": str,
    }
    options: dict[str, Any] = {"preset_index": preset_index}
    for key, expected_type in allowed_optional_fields.items():
        if key not in payload or payload[key] is None:
            continue
        value = payload[key]
        if expected_type is int:
            value = int(value)
            if value < 1 or value > 8:
                raise ValueError("sections must be between 1 and 8.")
        elif expected_type is bool:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean.")
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be a string.")
        if key == "storage_mode":
            value = value.strip().lower()
            if value not in {"local", "remote", "r2", "oss"}:
                raise ValueError("storage_mode must be one of: local, remote, r2, oss.")
        if key == "generation_profile":
            value = value.strip().lower()
            if value not in {"speed", "balanced", "quality"}:
                raise ValueError("generation_profile must be one of: speed, balanced, quality.")
        if key == "story_type":
            value = value.strip().lower()
            if value not in {"informative", "story", "how-to", "listicle", "analysis"}:
                raise ValueError("story_type must be one of: informative, story, how-to, listicle, analysis.")
        options[key] = value

    # key_points handling (list type)
    if "key_points" in payload and payload["key_points"] is not None:
        key_points = payload["key_points"]
        if isinstance(key_points, str):
            key_points = [p.strip() for p in key_points.split(",") if p.strip()]
        elif not isinstance(key_points, list):
            raise ValueError("key_points must be a list or comma-separated string")
        else:
            key_points = [str(point).strip() for point in key_points if str(point).strip()]
        if key_points:
            options["key_points"] = key_points

    return options


def preset_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "name",
            "topic",
            "audience",
            "tone",
            "section_count",
            "use_web_search",
            "image_style",
            "aspect_ratio",
            "resolution",
        ],
        "properties": {
            "name": {"type": "string"},
            "topic": {"type": "string"},
            "audience": {"type": "string"},
            "tone": {"type": "string"},
            "section_count": {"type": "integer", "minimum": 1, "maximum": 8},
            "use_web_search": {"type": "boolean"},
            "image_style": {"type": "string"},
            "aspect_ratio": {"type": "string", "enum": ["16:9", "4:3", "3:4", "1:1", "9:16"]},
            "resolution": {"type": "string", "enum": ["1k", "2k"]},
        },
    }


def clean_generated_preset(payload: dict[str, Any]) -> dict[str, Any]:
    # Fill in missing fields with defaults
    if not payload.get("aspect_ratio"):
        payload["aspect_ratio"] = "16:9"
    if not payload.get("resolution"):
        payload["resolution"] = "2k"

    # 处理 tone 可能是对象的情况
    if isinstance(payload.get("tone"), dict):
        # 如果 tone 是一个对象，转换成字符串描述
        tone_obj = payload["tone"]
        tone_parts = []
        if "emotional_temperature" in tone_obj:
            tone_parts.append(tone_obj["emotional_temperature"])
        if "screen_feel" in tone_obj:
            tone_parts.append(tone_obj["screen_feel"])
        if "expression_style" in tone_obj:
            tone_parts.append(tone_obj["expression_style"])
        payload["tone"] = "、".join(tone_parts) if tone_parts else "专业、清晰"

    preset = asdict(generator.CreativePreset.from_dict(payload))
    image_style = preset.get("image_style", "") or ""
    image_style = image_style.strip()
    if image_style and "no text overlay" not in image_style.lower():
        image_style = f"{image_style}, no text overlay"
    elif not image_style:
        image_style = "modern, professional, no text overlay"
    preset["image_style"] = image_style
    if preset["resolution"] not in {"1k", "2k"}:
        preset["resolution"] = "2k"
    if preset["aspect_ratio"] not in {"16:9", "4:3", "3:4", "1:1", "9:16"}:
        preset["aspect_ratio"] = "16:9"
    return _ensure_chinese_preset_fields(preset)


def _is_mostly_chinese(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    alpha_count = len(re.findall(r"[A-Za-z]", text))
    # 至少有中文，且中文数量不低于英文字符数量，视为“主要中文”。
    return cjk_count > 0 and cjk_count >= alpha_count


def _needs_chinese_rewrite(preset: dict[str, Any]) -> bool:
    for key in ("name", "topic", "audience", "tone"):
        if not _is_mostly_chinese(str(preset.get(key, ""))):
            return True
    return False


def _ensure_chinese_preset_fields(preset: dict[str, Any]) -> dict[str, Any]:
    """尽量保证灵感关键字段为中文（image_style 保持英文）。"""

    if not _needs_chinese_rewrite(preset):
        return preset

    generator.log_progress("Preset language check: non-Chinese fields detected, starting Chinese rewrite.")
    rewrite_prompt = (
        "请将下面这个 JSON 预设改写为中文版本，只改写 name/topic/audience/tone 四个字段，"
        "其他字段保持原值。要求：\n"
        "1) name/topic/audience/tone 必须是简体中文；\n"
        "2) image_style 必须保持英文并包含 no text overlay；\n"
        "3) 返回且仅返回一个合法 JSON 对象，不要 markdown。\n\n"
        f"原始 JSON：\n{json.dumps(preset, ensure_ascii=False)}"
    )
    try:
        rewritten = _call_text_generation_api(
            rewrite_prompt,
            model_priority=[("vertex", "gemini-2.5-flash"), ("grok", "grok-4-fast-non-reasoning")],
            race_mode=True,
        )
        data = json.loads(rewritten)
        if isinstance(data, dict):
            # 只覆盖目标字段，避免模型改坏其他结构
            for key in ("name", "topic", "audience", "tone"):
                if key in data and isinstance(data[key], str) and data[key].strip():
                    preset[key] = data[key].strip()
    except Exception as exc:  # noqa: BLE001
        generator.log_progress(f"Chinese preset rewrite skipped due to error: {exc}")
    # 二次兜底：如果仍有字段不是中文，逐字段强制改写，尽量保证最终输出中文。
    for key in ("name", "topic", "audience", "tone"):
        value = str(preset.get(key, "")).strip()
        if not value or _is_mostly_chinese(value):
            continue
        forced = _rewrite_field_to_chinese(key, value, preset)
        if forced:
            preset[key] = forced
    return preset


def _rewrite_field_to_chinese(field: str, value: str, preset: dict[str, Any]) -> str:
    """将单个字段强制改写为中文，失败时返回原值。"""

    prompt = (
        f"请把下面 {field} 字段改写为简体中文，保留原意并适合微信公众号选题预设。\n"
        "要求：\n"
        "1) 只输出改写后的中文文本；\n"
        "2) 不要引号，不要解释；\n"
        "3) 语言自然，避免机器翻译腔。\n\n"
        f"字段原文：{value}\n"
        f"上下文topic：{preset.get('topic', '')}\n"
        f"上下文audience：{preset.get('audience', '')}\n"
    )
    try:
        text = _call_text_generation_api(
            prompt,
            model_priority=[("vertex", "gemini-2.5-flash"), ("grok", "grok-4-fast-non-reasoning")],
            race_mode=False,
        ).strip()
        if text and _is_mostly_chinese(text):
            return text
    except Exception as exc:  # noqa: BLE001
        generator.log_progress(f"Field chinese rewrite failed for {field}: {exc}")
    return value


def build_xai_client(timeout_seconds: int = 180) -> generator.XAIHttpClient:
    generator.load_project_dotenv()
    api_key = generator.SCRIPT_API_KEY or generator.resolve_api_key()
    if not api_key:
        raise ValueError("Missing xAI API key. Set XAI_API_KEY in .env or environment.")
    return generator.XAIHttpClient(
        generator.XAIConfig(
            api_key=api_key,
            base_url=os.getenv("XAI_BASE_URL", generator.SCRIPT_BASE_URL).rstrip("/"),
            text_model=os.getenv("XAI_TEXT_MODEL", generator.SCRIPT_TEXT_MODEL),
            image_model=os.getenv("XAI_IMAGE_MODEL", generator.SCRIPT_IMAGE_MODEL),
            timeout_seconds=timeout_seconds,
            retry_attempts=generator.SCRIPT_RETRY_ATTEMPTS,
            retry_backoff_seconds=generator.SCRIPT_RETRY_BACKOFF_SECONDS,
        )
    )


def expand_idea_to_full_params(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert user idea to full article generation parameters including outline, key_points, story_type."""
    idea = payload.get("idea")
    reference_image_url = payload.get("reference_image_url")  # 从payload提取参考图
    if not isinstance(idea, str) or not idea.strip():
        raise ValueError("idea is required and must be a non-empty string.")

    system_prompt = """你是一个中文内容策划专家。你必须用中文思考和回复。

你的任务：将用户的想法扩展成完整的文章生成计划。

返回JSON对象（必须包含这些字段）：
{
  "topic": "用中文写的具体文章主题",
  "audience": "用中文描述的目标受众",
  "tone": "用中文描述的文章风格和语调",
  "sections": 4,
  "outline": "用中文写的结构化大纲，格式：1. 章节标题 2. 章节标题 3. 章节标题 4. 章节标题",
  "key_points": ["用中文写的要点1", "用中文写的要点2", "用中文写的要点3"],
  "story_type": "how-to|story|listicle|analysis|informative",
  "needs_reference_image": true/false,
  "reference_image_guidance": "如果需要参考图，请给出建议，否则留空",
  "use_web_search": false,
  "image_style": "visual style in English",
  "aspect_ratio": "16:9|1:1|3:4",
  "resolution": "1k|2k"
}

严格要求：
- topic 必须用中文
- audience 必须用中文
- tone 必须用中文
- outline 必须用中文，格式为 "1. xxx 2. xxx 3. xxx 4. xxx"
- key_points 中的每一项都必须用中文
- needs_reference_image: 判断该内容是否需要参考图来保持视觉/人物一致性
  * true 如果内容涉及：具体人物、个人成长故事、人物形象、视觉场景的连贯性
  * false 如果内容是：纯教程、列表、分析、知识分享等不涉及具体人物的内容
- reference_image_guidance: 如果 needs_reference_image=true，提供参考图的使用建议（中文）
- 只返回JSON，不要任何其他文本"""

    generator.log_progress("Expanding idea to full parameters (Chinese)...")

    # 强制用中文回答：提供中文JSON范例
    full_prompt = f"""{system_prompt}

用户想法：
{idea.strip()}

请按照以下JSON格式用中文回答（topic, audience, tone, outline, key_points 必须是中文）：

示例格式：
{{
  "topic": "中文标题示例",
  "audience": "中文受众描述示例",
  "tone": "中文风格描述示例",
  "sections": 4,
  "outline": "1. 中文章节标题 2. 中文章节标题 3. 中文章节标题 4. 中文章节标题",
  "key_points": ["中文要点示例1", "中文要点示例2", "中文要点示例3"],
  "story_type": "how-to",
  "use_web_search": false,
  "image_style": "visual style in English",
  "aspect_ratio": "16:9",
  "resolution": "2k"
}}

现在请根据用户想法生成JSON（必须用中文！）："""

    response_text = _call_text_generation_api(full_prompt, race_mode=True)

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
            data = json.loads(json_str)
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
            data = json.loads(json_str)
        else:
            raise ValueError(f"Response was not valid JSON: {response_text[:500]}")

    # Validate required fields
    required = ["topic", "audience", "tone", "sections", "outline", "key_points", "story_type"]
    for field in required:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    # Ensure key_points is a list
    if isinstance(data["key_points"], str):
        data["key_points"] = [p.strip() for p in data["key_points"].split(",")]
    if not isinstance(data["key_points"], list):
        raise ValueError("key_points must be a list of strings")

    # Set defaults for optional fields
    data.setdefault("use_web_search", False)
    data.setdefault("image_style", "professional illustration, clean composition, no text overlay")
    data.setdefault("aspect_ratio", "16:9")
    data.setdefault("resolution", "2k")

    # 强制中文化：确保关键字段都是中文
    chinese_fields = ["topic", "audience", "tone", "outline"]
    for field in chinese_fields:
        value = str(data.get(field, "")).strip()
        if value and not _is_mostly_chinese(value):
            generator.log_progress(f"Field '{field}' is not Chinese, attempting to rewrite...")
            rewritten = _rewrite_field_to_chinese(field, value, data)
            if rewritten:
                data[field] = rewritten
            else:
                generator.log_progress(f"Warning: Failed to rewrite '{field}' to Chinese")

    # 强制中文化 key_points
    if isinstance(data["key_points"], list):
        rewritten_points = []
        for i, point in enumerate(data["key_points"]):
            point_str = str(point).strip()
            if point_str and not _is_mostly_chinese(point_str):
                generator.log_progress(f"Key point {i} is not Chinese, attempting to rewrite...")
                prompt = (
                    f"请把下面的要点改写为简体中文，保留原意：\n"
                    f"原文：{point_str}\n"
                    f"要求：只输出改写后的中文文本，不要引号，不要解释。"
                )
                try:
                    rewritten = _call_text_generation_api(
                        prompt,
                        model_priority=[("vertex", "gemini-2.5-flash"), ("grok", "grok-4-fast-non-reasoning")],
                        race_mode=False,
                    ).strip()
                    if rewritten and _is_mostly_chinese(rewritten):
                        point_str = rewritten
                except Exception as exc:  # noqa: BLE001
                    generator.log_progress(f"Key point {i} rewrite failed: {exc}")
            rewritten_points.append(point_str)
        data["key_points"] = rewritten_points

    result = {
        "topic": data["topic"],
        "audience": data["audience"],
        "tone": data["tone"],
        "sections": int(data["sections"]),
        "outline": data["outline"],
        "key_points": data["key_points"],
        "story_type": data.get("story_type", "informative"),
        "needs_reference_image": bool(data.get("needs_reference_image", False)),
        "reference_image_guidance": data.get("reference_image_guidance", ""),
        "use_web_search": bool(data.get("use_web_search", False)),
        "image_style": data.get("image_style", "professional illustration, clean composition, no text overlay"),
        "aspect_ratio": data.get("aspect_ratio", "16:9"),
        "resolution": data.get("resolution", "2k"),
    }

    # 添加参考图支持（可选）
    if reference_image_url:
        result["reference_image_url"] = reference_image_url
        result["reference_character_profile"] = (
            "以参考图中的女性为唯一主角：年轻东亚女性，长黑色微卷发，白皙皮肤，鹅蛋脸，大眼睛，精致淡妆，"
            "白色上衣，珍珠项链。所有配图都必须保持同一人物的脸型、眼睛、发色、气质和辨识度，只改变年龄阶段、服装和场景。"
        )

    return result


def complete_creative_preset(payload: dict[str, Any]) -> dict[str, Any]:
    idea = payload.get("idea")
    partial = payload.get("preset", payload.get("partial", payload))
    if partial is payload:
        partial = {key: value for key, value in payload.items() if key not in {"idea"}}
    if idea is not None and not isinstance(idea, str):
        raise ValueError("idea must be a string.")
    if not isinstance(partial, dict):
        raise ValueError("preset or partial must be a JSON object.")
    if not idea and not partial:
        raise ValueError("Provide idea, preset, partial, or preset fields to complete.")

    system_prompt = """你是微信公众号选题与栏目策划总监。你的任务是把不完整创意预设补全成“可直接投产”的高质量预设。

高质量标准（必须同时满足）：
1. 保持原始创意方向，不偏题；优先保留用户已给信息。
2. topic 必须具体到可写（不是口号），应包含明确场景/冲突/价值点。
3. audience 必须是可识别人群（身份 + 阶段 + 核心诉求），避免“泛人群”。
4. tone 要能指导写作风格，包含至少两个维度（如情绪温度、叙事方式、表达节奏）。
5. section_count 以 3-4 为优先，除非题材明显需要更多结构。
6. image_style 必须是英文、可视化、可执行，且强制包含 "no text overlay"。
7. 所有字段之间要互相一致：topic、audience、tone、image_style 不能冲突。
8. 只输出一个 JSON 对象，不要 markdown、不要解释、不要注释。"""

    partial_str = json.dumps(partial, ensure_ascii=False, indent=2)
    user_prompt = f"""请补全并改进下面的创意预设，使其达到可直接用于文章生成的质量：

{"当前想法：" + idea if idea else ""}

{"当前预设（不完整）：" + partial_str if partial else ""}

要求：
- 返回一个完整 JSON 对象，字段必须且仅包含：
  name, topic, audience, tone, section_count, use_web_search, image_style, aspect_ratio, resolution
- name：12字以内，突出差异化定位，不要泛词（如“优质内容”）
- topic：一句话写清主问题 + 受众收益，避免空泛
- audience：越具体越好（如“8-12岁孩子家长，担心学习内驱力不足”）
- tone：给出可执行的表达风格，不要抽象词堆砌
- image_style：英文、具体、包含 "no text overlay"，避免空泛形容词
- aspect_ratio 仅可为：16:9, 4:3, 3:4, 1:1, 9:16
- resolution 仅可为：1k 或 2k
- section_count 范围 1-8，优先 3 或 4
- 返回纯 JSON，不要代码块，不要任何解释文本"""

    prompt_to_send = f"{system_prompt}\n\n{user_prompt}"

    generator.log_progress("Completing creative preset (racing all models)...")
    # 使用竞速模式加快补全速度
    response_text = _call_text_generation_api(prompt_to_send, race_mode=True)

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        # 尝试从markdown代码块中提取
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
            data = json.loads(json_str)
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
            data = json.loads(json_str)
        else:
            raise ValueError(f"Response was not valid JSON: {response_text[:500]}")

    return clean_generated_preset(data)


def _call_text_generation_api(prompt: str, model_priority: list[tuple[str, str]] | None = None, race_mode: bool = False) -> str:
    """调用高质量文本生成接口，支持竞速或降级模式。

    Args:
        prompt: 提示词
        model_priority: [(provider, model), ...] 优先级列表
        race_mode: True 为竞速模式（并发所有模型），False 为降级模式（顺序尝试）

    Returns:
        生成的文本内容
    """
    if model_priority is None:
        # 默认优先级：Vertex 优先，Grok 仅作为兜底。
        model_priority = [
            ("vertex", "gemini-2.5-pro"),
            ("vertex", "gemini-2.5-flash"),
            ("grok", "grok-4-fast-non-reasoning"),
            ("grok", "grok-4-fast-reasoning"),
        ]

    import requests

    def call_single_model(provider: str, model: str) -> tuple[bool, str, str]:
        """调用单个模型，返回 (成功, 文本或错误, 模型名)"""
        try:
            payload = {
                "provider": provider,
                "model": model,
                "prompt": prompt,
            }
            response = requests.post(
                "https://images.vyibc.com/api/v1beta/text:generate",
                json=payload,
                timeout=240,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                return False, error_msg, f"{provider}/{model}"

            text = data.get("text", "").strip()
            if text:
                return True, text, f"{provider}/{model}"
            else:
                return False, "Empty response", f"{provider}/{model}"
        except Exception as e:
            return False, str(e), f"{provider}/{model}"

    # 竞速模式：并发请求所有模型，返回最快的
    if race_mode:
        generator.log_progress(f"Racing {len(model_priority)} models in parallel...")
        with ThreadPoolExecutor(max_workers=len(model_priority)) as executor:
            futures = {
                executor.submit(call_single_model, provider, model): (provider, model)
                for provider, model in model_priority
            }

            for future in as_completed(futures):
                success, result, model_name = future.result()
                if success:
                    generator.log_progress(f"✓ Fastest model: {model_name}")
                    return result

        # 所有模型都失败了
        raise RuntimeError("All models failed in race mode")

    # 降级模式：顺序尝试模型
    else:
        last_error = None
        for provider, model in model_priority:
            success, result, model_name = call_single_model(provider, model)
            if success:
                if (provider, model) != model_priority[0]:
                    generator.log_progress(f"Using fallback model {model_name}")
                return result
            else:
                generator.log_progress(f"Model {model_name} failed: {result}, trying next...")
                last_error = result

        raise RuntimeError(f"All text generation models failed. Last error: {last_error}")


def generate_creative_presets(payload: dict[str, Any]) -> dict[str, Any]:
    brief = payload.get("brief") or payload.get("topic") or payload.get("idea")
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("brief is required and must be a non-empty string.")
    count = int(payload.get("count", 5))
    if count < 1 or count > 10:
        raise ValueError("count must be between 1 and 10.")

    defaults = {
        key: payload[key]
        for key in ("audience", "tone", "use_web_search", "image_style", "aspect_ratio", "resolution")
        if key in payload
    }

    system_prompt = """你是微信公众号内容策略负责人。你的目标是产出“可直接开写”的高质量创意预设集合。

核心要求：
1. 质量优先：每个预设都要完整、具体、可执行，避免空话和套话。
2. 差异化优先：预设之间必须显著不同，至少覆盖不同读者细分、叙事角度、价值主张。
3. 传播性优先：topic 需要兼顾点击动机与阅读价值，避免标题党。
4. 一致性：name/topic/audience/tone/section_count/image_style 必须前后一致，不冲突。
5. 结构控制：section_count 推荐 3-4；仅在必要时提高。
6. 视觉可执行：image_style 必须是英文，并包含 "no text overlay"。

输出约束：
- 只输出一个 JSON 对象，形如 {"presets":[...]}
- 不允许输出 markdown、解释、注释或额外字段。"""

    user_prompt = f"""基于以下创意简报，生成 {count} 个高质量且彼此明显不同的 WeChat 文章创意预设：

创意简报：
{brief.strip()}

{'当前偏好设置：' + json.dumps(defaults, ensure_ascii=False) if defaults else ''}

要求：
- 生成 {count} 个预设；每个预设必须包含：
  name, topic, audience, tone, section_count, use_web_search, image_style, aspect_ratio, resolution
- 各预设必须在以下至少两项上明显不同：目标读者、切入角度、叙事方式、行动导向
- name：简短有辨识度（不超过 12 字，避免重复词）
- topic：具体到可写，体现“问题场景 + 价值收益”
- audience：精准细分，不得写“所有人/大众”
- tone：可执行（如“温暖叙事 + 数据点穿插 + 行动清单收束”）
- section_count：1-8，优先 3 或 4
- image_style：英文且包含 "no text overlay"
- aspect_ratio：16:9 / 4:3 / 3:4 / 1:1 / 9:16
- resolution：1k 或 2k
- 仅返回 JSON 对象，不要代码块和解释文本"""

    prompt_to_send = f"{system_prompt}\n\n用户请求：\n{user_prompt}"

    # 调用高质量文本生成API，获取创意预设
    # 预设生成使用竞速模式，哪个模型最快就用哪个
    generator.log_progress(f"Generating {count} creative presets (racing all models for speed)...")

    # 为预设生成使用竞速模式，同时请求所有模型
    response_text = _call_text_generation_api(prompt_to_send, race_mode=True)

    try:
        # 从响应中提取JSON
        data = json.loads(response_text)
    except json.JSONDecodeError:
        # 如果直接不是JSON，尝试从markdown代码块中提取
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
            data = json.loads(json_str)
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
            data = json.loads(json_str)
        else:
            raise ValueError(f"Response was not valid JSON: {response_text[:500]}")

    presets = data.get("presets")
    if not isinstance(presets, list):
        raise ValueError(f"Model response did not contain presets array. Got: {data}")

    if len(presets) < count:
        generator.log_progress(f"Warning: Expected {count} presets but got {len(presets)}")

    return {"presets": [clean_generated_preset(item) for item in presets]}


def start_generation_job(payload: dict[str, Any]) -> dict[str, Any]:
    options = coerce_article_payload(payload)
    job_id = create_job_id()
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "request": options,
        "result": None,
        "error": None,
        "logs": [],
    }
    save_job(job)
    thread = threading.Thread(target=run_generation_job, args=(job_id, options), daemon=True)
    thread.start()
    return job


def status_for_generation_log(message: str) -> str | None:
    if "Reviewing article draft" in message or "Revising article draft" in message:
        return "reviewing"
    if "Generating " in message and " images concurrently" in message:
        return "generating_images"
    if message.startswith("Rendering ") or message.startswith("Writing output"):
        return "rendering"
    if message.startswith("Uploading output files"):
        return "uploading"
    return None


def run_generation_job(job_id: str, options: dict[str, Any]) -> None:
    job = load_job(job_id)
    if job is None:
        return
    append_log(job, "Waiting for generation slot")
    GENERATION_LOCK.acquire()

    original_log_progress = generator.log_progress

    def job_log(message: str) -> None:
        original_log_progress(message)
        current = load_job(job_id)
        if current is not None:
            next_status = status_for_generation_log(message)
            if next_status is not None:
                current["status"] = next_status
                current["updated_at"] = utc_now()
            append_log(current, message)

    generator.log_progress = job_log
    try:
        job["status"] = "running"
        job["started_at"] = utc_now()
        job["updated_at"] = utc_now()
        save_job(job)
        append_log(job, "Job started")

        bundle = generator.generate_wechat_article(output_dir=output_dir_for_job(job_id), **options)
        job = load_job(job_id) or job
        job["status"] = "succeeded"
        job["updated_at"] = utc_now()
        job["finished_at"] = utc_now()
        job["result"] = {
            **(bundle.public_urls or resolve_result_links(job_id, output_dir_for_job(job_id))),
            "title": bundle.draft.title,
            "summary": bundle.draft.summary,
            "tags": bundle.draft.tags,
            "image_count": 1 + len(bundle.section_images),
        }
        save_job(job)
        append_log(job, "Job finished")
    except BaseException as exc:
        job = load_job(job_id) or job
        job["status"] = "failed"
        job["updated_at"] = utc_now()
        job["finished_at"] = utc_now()
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["traceback"] = traceback.format_exc()
        save_job(job)
        append_log(job, f"Job failed: {job['error']}")
    finally:
        generator.log_progress = original_log_progress
        GENERATION_LOCK.release()


def write_json(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: dict[str, Any] | list[Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _safe_json_dumps(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return repr(data)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...<truncated {len(text) - max_chars} chars>"


def log_api_io(path: str, request_payload: Any, response_status: HTTPStatus, response_payload: Any) -> None:
    """打印接口入参/出参日志，便于线上排查。"""

    if not API_IO_LOG_ENABLED:
        return
    req_text = _truncate_text(_safe_json_dumps(request_payload), API_IO_LOG_MAX_CHARS)
    res_text = _truncate_text(_safe_json_dumps(response_payload), API_IO_LOG_MAX_CHARS)
    generator.log_progress(
        f"API_IO path={path} status={int(response_status)} request={req_text} response={res_text}"
    )


def write_text(handler: BaseHTTPRequestHandler, status: HTTPStatus, body: str, content_type: str) -> None:
    raw = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def write_file(handler: BaseHTTPRequestHandler, path: Path) -> None:
    content_type = content_type_for_path(path)
    body = path.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def content_type_for_path(path: Path) -> str:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() in {".html", ".htm"}:
        return "text/html; charset=utf-8"
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    if path.suffix.lower() == ".json":
        return "application/json; charset=utf-8"
    if path.suffix.lower() in {".txt", ".log", ".css", ".js"} or content_type.startswith("text/"):
        return f"{content_type}; charset=utf-8"
    return content_type


def request_base_url(handler: BaseHTTPRequestHandler) -> str:
    """Build external base URL from the incoming request headers."""

    forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    proto = forwarded_proto if forwarded_proto else "http"
    host = handler.headers.get("Host", f"{HOST}:{PORT}")
    return f"{proto}://{host}"


def render_docs_html(handler: BaseHTTPRequestHandler) -> str:
    """Render docs with request-aware base URL."""

    return DOCS_HTML.replace("http://127.0.0.1:8765", request_base_url(handler))


def list_jobs() -> list[dict[str, Any]]:
    if not JOB_STATE_DIR.exists():
        return []
    jobs = []
    for path in sorted(JOB_STATE_DIR.glob("*.json"), reverse=True):
        try:
            with JOB_STATE_LOCK:
                jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return jobs


def api_schema() -> dict[str, Any]:
    return {
        "schemas": {
            "ArticleResult": {
                "type": "object",
                "required": [
                    "request",
                    "draft",
                    "cover_image",
                    "section_images",
                    "generated_at",
                    "links",
                ],
                "properties": {
                    "request": {"$ref": "#/schemas/ArticleRequest"},
                    "draft": {"$ref": "#/schemas/ArticleDraft"},
                    "cover_image": {"$ref": "#/schemas/GeneratedImage"},
                    "section_images": {"type": "array", "items": {"$ref": "#/schemas/GeneratedImage"}},
                    "generated_at": {"type": "string", "format": "date-time"},
                    "links": {"$ref": "#/schemas/ResultLinks"},
                },
            },
            "ArticleRequest": {
                "type": "object",
                "required": [
                    "topic",
                    "audience",
                    "tone",
                    "sections",
                    "use_web_search",
                    "image_style",
                    "aspect_ratio",
                    "resolution",
                ],
                "properties": {
                    "topic": {"type": "string"},
                    "audience": {"type": "string"},
                    "tone": {"type": "string"},
                    "sections": {"type": "integer"},
                    "use_web_search": {"type": "boolean"},
                    "image_style": {"type": "string"},
                    "aspect_ratio": {"type": "string"},
                    "resolution": {"type": "string"},
                    "outline": {"type": ["string", "null"], "description": "Article outline, e.g. '1. Background 2. Problem 3. Solution 4. Action'"},
                    "key_points": {"type": ["array", "null"], "items": {"type": "string"}, "description": "List of key points to cover in the article"},
                    "story_type": {"type": "string", "enum": ["informative", "story", "how-to", "listicle", "analysis"], "description": "Article type (default: 'informative')"},
                    "needs_reference_image": {"type": "boolean", "description": "Whether this content needs a reference image to maintain visual/character consistency (AI-determined)"},
                    "reference_image_guidance": {"type": "string", "description": "Guidance on how to use the reference image (in Chinese) if needs_reference_image is true"},
                    "reference_image_url": {"type": ["string", "null"], "description": "Reference image URL for maintaining visual consistency in narrative-based content"},
                    "reference_character_profile": {"type": ["string", "null"], "description": "Concrete visual character profile to preserve across generated images"},
                },
            },
            "ArticleDraft": {
                "type": "object",
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
                    "intro_paragraphs": {"type": "array", "items": {"type": "string"}},
                    "sections": {"type": "array", "items": {"$ref": "#/schemas/ArticleSection"}},
                    "conclusion_title": {"type": "string"},
                    "conclusion_paragraphs": {"type": "array", "items": {"type": "string"}},
                    "call_to_action": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
            "ArticleSection": {
                "type": "object",
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
                    "paragraphs": {"type": "array", "items": {"type": "string"}},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "takeaway": {"type": "string"},
                    "image_prompt": {"type": "string"},
                    "image_alt": {"type": "string"},
                    "image_caption": {"type": "string"},
                },
            },
            "GeneratedImage": {
                "type": "object",
                "required": ["prompt", "source_url", "alt_text", "caption"],
                "properties": {
                    "prompt": {"type": "string"},
                    "source_url": {"type": "string"},
                    "alt_text": {"type": "string"},
                    "caption": {"type": "string"},
                    "revised_prompt": {"type": ["string", "null"]},
                    "local_path": {"type": ["string", "null"]},
                },
            },
            "ResultLinks": {
                "type": "object",
                "required": [
                    "article_html",
                    "article_markdown",
                    "article_json",
                    "draft_markdown",
                    "draft_json",
                    "output_dir",
                ],
                "properties": {
                    "article_html": {"type": "string"},
                    "article_markdown": {"type": "string"},
                    "article_json": {"type": "string"},
                    "draft_markdown": {"type": "string"},
                    "draft_json": {"type": "string"},
                    "output_dir": {"type": "string"},
                },
            },
        }
    }


class GrokWechatHandler(BaseHTTPRequestHandler):
    server_version = "GrokWechatArticleServer/1.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", CORS_ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", CORS_ALLOW_METHODS)
        self.send_header("Access-Control-Allow-Headers", CORS_ALLOW_HEADERS)
        self.send_header("Access-Control-Max-Age", CORS_MAX_AGE)
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            write_text(self, HTTPStatus.OK, INDEX_HTML, "text/html; charset=utf-8")
            return
        if path == "/ui":
            write_text(self, HTTPStatus.OK, NEW_UI_HTML, "text/html; charset=utf-8")
            return
        if path == "/ui-flow":
            write_text(self, HTTPStatus.OK, FLOW_UI_HTML, "text/html; charset=utf-8")
            return
        if path == "/docs":
            write_text(self, HTTPStatus.OK, render_docs_html(self), "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path == "/api/presets":
            write_json(self, HTTPStatus.OK, {"presets": read_presets()})
            return
        if path == "/api/presets/raw":
            write_json(self, HTTPStatus.OK, read_raw_presets())
            return
        if path == "/api/schema":
            write_json(self, HTTPStatus.OK, api_schema())
            return
        if path == "/api/jobs":
            write_json(self, HTTPStatus.OK, {"jobs": list_jobs()})
            return
        if path.startswith("/api/jobs/"):
            self.handle_job_get(path)
            return
        if path.startswith("/outputs/"):
            self.handle_output_file(path)
            return
        write_json(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_HEAD(self) -> None:
        if self.path == "/":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        if self.path == "/docs":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        if self.path.startswith("/outputs/"):
            relative = unquote(self.path.removeprefix("/outputs/"))
            target = (OUTPUT_ROOT / relative).resolve()
            root = OUTPUT_ROOT.resolve()
            if str(target).startswith(str(root)) and target.is_file():
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type_for_path(target))
                self.send_header("Content-Length", str(target.stat().st_size))
                self.end_headers()
                return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path not in {"/api/articles", "/api/presets/complete", "/api/presets/generate", "/api/presets/expand-idea"}:
            write_json(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        if not require_api_key(self):
            return
        payload: dict[str, Any] | None = None
        try:
            payload = parse_json_body(self)
            if path == "/api/articles":
                job = start_generation_job(payload)
                log_api_io(path, payload, HTTPStatus.ACCEPTED, job)
                write_json(self, HTTPStatus.ACCEPTED, job)
            elif path == "/api/presets/complete":
                response_payload = {"preset": complete_creative_preset(payload)}
                log_api_io(path, payload, HTTPStatus.OK, response_payload)
                write_json(self, HTTPStatus.OK, response_payload)
            elif path == "/api/presets/expand-idea":
                response_payload = expand_idea_to_full_params(payload)
                log_api_io(path, payload, HTTPStatus.OK, response_payload)
                write_json(self, HTTPStatus.OK, response_payload)
            else:
                response_payload = generate_creative_presets(payload)
                log_api_io(path, payload, HTTPStatus.OK, response_payload)
                write_json(self, HTTPStatus.OK, response_payload)
        except ValueError as exc:
            response_payload = {"error": str(exc)}
            log_api_io(path, payload, HTTPStatus.BAD_REQUEST, response_payload)
            write_json(self, HTTPStatus.BAD_REQUEST, response_payload)
        except json.JSONDecodeError:
            response_payload = {"error": "Invalid JSON body."}
            log_api_io(path, payload, HTTPStatus.BAD_REQUEST, response_payload)
            write_json(self, HTTPStatus.BAD_REQUEST, response_payload)
        except generator.XAIAPIError as exc:
            response_payload = {"error": str(exc)}
            log_api_io(path, payload, HTTPStatus.BAD_GATEWAY, response_payload)
            write_json(self, HTTPStatus.BAD_GATEWAY, response_payload)

    def handle_job_get(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 3:
            write_json(self, HTTPStatus.NOT_FOUND, {"error": "Missing job id."})
            return
        job_id = parts[2]
        job = load_job(job_id)
        if job is None:
            write_json(self, HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"})
            return
        if len(parts) == 4 and parts[3] == "result":
            if job.get("status") != "succeeded":
                write_json(self, HTTPStatus.CONFLICT, {"error": "Job has not succeeded yet.", "job": job})
                return
            article_json = output_dir_for_job(job_id) / "article.json"
            if not article_json.exists():
                write_json(self, HTTPStatus.NOT_FOUND, {"error": "Result file is missing."})
                return
            result = json.loads(article_json.read_text(encoding="utf-8"))
            result["links"] = resolve_result_links(job_id)
            write_json(self, HTTPStatus.OK, result)
            return
        write_json(self, HTTPStatus.OK, job)

    def handle_output_file(self, path: str) -> None:
        relative = unquote(path.removeprefix("/outputs/"))
        target = (OUTPUT_ROOT / relative).resolve()
        root = OUTPUT_ROOT.resolve()
        if not str(target).startswith(str(root)) or not target.is_file():
            write_json(self, HTTPStatus.NOT_FOUND, {"error": "Output file not found."})
            return
        write_file(self, target)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grok WeChat Article Studio</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8f5;
      --surface: #ffffff;
      --ink: #17211c;
      --muted: #5f6d66;
      --line: #d9e0dc;
      --accent: #0e7c66;
      --accent-strong: #095f4f;
      --warn: #9a5b12;
      --bad: #a43d3d;
      --good: #147a42;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    .shell { max-width: 1180px; margin: 0 auto; padding: 28px 18px 40px; }
    header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
      padding-bottom: 22px;
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 30px; line-height: 1.15; font-weight: 760; }
    .subtle { color: var(--muted); margin: 8px 0 0; line-height: 1.6; }
    .status-pill {
      min-width: 132px;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 8px;
      padding: 10px 12px;
      font-weight: 650;
      text-align: center;
      color: var(--muted);
    }
    main { display: grid; grid-template-columns: minmax(300px, 380px) 1fr; gap: 22px; margin-top: 22px; }
    section {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    h2 { margin: 0 0 14px; font-size: 17px; line-height: 1.3; }
    label { display: block; margin-top: 14px; font-size: 13px; color: var(--muted); font-weight: 650; }
    select, input, textarea {
      width: 100%;
      margin-top: 7px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px 11px;
      color: var(--ink);
      background: #fbfcfa;
      font: inherit;
      min-height: 42px;
    }
    textarea { min-height: 92px; resize: vertical; line-height: 1.5; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    button, .button-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      min-height: 42px;
      border-radius: 7px;
      border: 1px solid transparent;
      padding: 10px 14px;
      font-weight: 700;
      font: inherit;
      cursor: pointer;
      text-decoration: none;
      transition: background-color 180ms ease, border-color 180ms ease, color 180ms ease;
    }
    button.primary { width: 100%; margin-top: 16px; background: var(--accent); color: #fff; }
    button.primary:hover { background: var(--accent-strong); }
    button.secondary, .button-link { background: #eef5f1; color: var(--accent-strong); border-color: #cfe1da; }
    button.secondary:hover, .button-link:hover { background: #e3eee9; }
    button:disabled { cursor: not-allowed; opacity: 0.62; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .inline-actions { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
    .inline-actions button { flex: 1 1 160px; }
    .divider { height: 1px; background: var(--line); margin: 18px 0; }
    .form-block {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfcfa;
      margin-top: 14px;
    }
    .form-block h3 { margin: 0 0 10px; font-size: 15px; }
    .check-row {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 14px;
      color: var(--muted);
      font-weight: 650;
    }
    .check-row input { width: 18px; min-height: 18px; margin: 0; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 13px; background: #fbfcfa; min-height: 76px; }
    .metric span { display: block; color: var(--muted); font-size: 12px; font-weight: 650; }
    .metric strong { display: block; margin-top: 8px; font-size: 17px; line-height: 1.3; word-break: break-word; }
    .log {
      min-height: 330px;
      max-height: 520px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #111c18;
      color: #d7eee4;
      padding: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.55;
      white-space: pre-wrap;
    }
    .empty { color: var(--muted); padding: 18px 0; line-height: 1.7; }
    .ok { color: var(--good); }
    .bad { color: var(--bad); }
    .warn { color: var(--warn); }
    svg { width: 18px; height: 18px; flex: 0 0 auto; }
    @media (max-width: 860px) {
      header { display: block; }
      .status-pill { margin-top: 14px; text-align: left; }
      main { grid-template-columns: 1fr; }
      .grid { grid-template-columns: 1fr; }
      .row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>Grok WeChat Article Studio</h1>
        <p class="subtle">生成公众号文章、封面图和正文配图，并通过 HTTP API 对外提供同一套能力。<a href="/docs">查看接口文档</a></p>
      </div>
      <div id="statusPill" class="status-pill">Idle</div>
    </header>
    <main>
      <section>
        <h2>生成配置</h2>
        <div class="form-block">
          <h3>灵感池</h3>
          <label for="preset">当前灵感</label>
          <select id="preset"></select>
          <label for="presetBrief">换一批方向</label>
          <textarea id="presetBrief" placeholder="可选，例如：面向家长的 AI 教育公众号选题"></textarea>
          <div class="row">
            <div>
              <label for="presetCount">每批数量</label>
              <input id="presetCount" type="number" min="1" max="10" value="5">
            </div>
            <div>
              <label for="presetAspect">偏好比例</label>
              <input id="presetAspect" placeholder="留空自动变化">
            </div>
          </div>
          <div class="inline-actions">
            <button id="generatePresets" class="secondary" type="button">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
              换一批灵感
            </button>
          </div>
        </div>
        <div class="form-block">
          <h3>指定创意</h3>
          <label for="completeIdea">创意描述</label>
          <textarea id="completeIdea" placeholder="例如：未来生活方式想象"></textarea>
          <div class="inline-actions">
            <button id="completePreset" class="secondary" type="button">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>
              确定创意
            </button>
          </div>
        </div>
        <div class="form-block">
          <h3>文章设定</h3>
          <label for="topic">主题</label>
          <textarea id="topic" placeholder="选择或确认灵感后自动填入"></textarea>
          <label for="audience">目标读者</label>
          <textarea id="audience" placeholder="选择或确认灵感后自动填入"></textarea>
          <label for="tone">语气</label>
          <input id="tone" placeholder="选择或确认灵感后自动填入">
          <div class="row">
            <div>
              <label for="sections">小节数</label>
              <input id="sections" type="number" min="1" max="8" placeholder="自动">
            </div>
            <div>
              <label for="aspect">图片比例</label>
              <input id="aspect" placeholder="自动">
            </div>
          </div>
          <div class="row">
            <div>
              <label for="resolution">清晰度</label>
              <input id="resolution" placeholder="1k 或 2k">
            </div>
            <div>
              <label for="storageMode">存储模式</label>
              <select id="storageMode">
                <option value="local" selected>local（Studio 内预览推荐）</option>
                <option value="remote">remote（优先 R2，缺配置回落 OSS）</option>
                <option value="r2">r2（上传 Cloudflare R2）</option>
                <option value="oss">oss（上传阿里云 OSS）</option>
              </select>
            </div>
            <div>
              <label for="generationProfile">生成策略</label>
              <select id="generationProfile">
                <option value="speed">速度优先（更快返回）</option>
                <option value="balanced" selected>均衡（默认）</option>
                <option value="quality">质量优先（更高质量）</option>
              </select>
            </div>
            <label class="check-row" for="useWebSearch">
              <input id="useWebSearch" type="checkbox">
              联网补充事实
            </label>
          </div>
          <label for="style">视觉风格</label>
          <textarea id="style" placeholder="选择或确认灵感后自动填入"></textarea>
        </div>
        <button id="generate" class="primary" type="button">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
          开始生成
        </button>
      </section>
      <div>
        <section>
          <h2>任务结果</h2>
          <div class="grid">
            <div class="metric"><span>任务 ID</span><strong id="jobId">-</strong></div>
            <div class="metric"><span>状态</span><strong id="jobStatus">-</strong></div>
            <div class="metric"><span>标题</span><strong id="title">-</strong></div>
            <div class="metric"><span>图片数量</span><strong id="imageCount">-</strong></div>
          </div>
          <div id="links" class="toolbar"></div>
          <div id="message" class="empty">还没有任务。点击左侧按钮开始生成。</div>
        </section>
        <section style="margin-top: 18px;">
          <h2>运行日志</h2>
          <div id="log" class="log"></div>
        </section>
        <section style="margin-top: 18px;">
          <h2>页面预览</h2>
          <div id="previewHint" class="empty">生成成功后会在这里直接预览 article.html。</div>
          <iframe
            id="previewFrame"
            title="article preview"
            style="display:none;width:100%;min-height:680px;border:1px solid var(--line);border-radius:8px;background:#fff;"
          ></iframe>
        </section>
      </div>
    </main>
  </div>
  <script>
    const presetSelect = document.getElementById("preset");
    const topicInput = document.getElementById("topic");
    const audienceInput = document.getElementById("audience");
    const toneInput = document.getElementById("tone");
    const sectionsInput = document.getElementById("sections");
    const aspectInput = document.getElementById("aspect");
    const resolutionInput = document.getElementById("resolution");
    const storageModeInput = document.getElementById("storageMode");
    const generationProfileInput = document.getElementById("generationProfile");
    const useWebSearchInput = document.getElementById("useWebSearch");
    const styleInput = document.getElementById("style");
    const presetBriefInput = document.getElementById("presetBrief");
    const presetCountInput = document.getElementById("presetCount");
    const presetAspectInput = document.getElementById("presetAspect");
    const completeIdeaInput = document.getElementById("completeIdea");
    const generatePresetsButton = document.getElementById("generatePresets");
    const completePresetButton = document.getElementById("completePreset");
    const generateButton = document.getElementById("generate");
    const statusPill = document.getElementById("statusPill");
    const jobId = document.getElementById("jobId");
    const jobStatus = document.getElementById("jobStatus");
    const title = document.getElementById("title");
    const imageCount = document.getElementById("imageCount");
    const links = document.getElementById("links");
    const message = document.getElementById("message");
    const logBox = document.getElementById("log");
    const previewHint = document.getElementById("previewHint");
    const previewFrame = document.getElementById("previewFrame");
    let pollTimer = null;
    let dynamicPresetCounter = 1000;

    function iconPath(name) {
      if (name === "open") return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>';
    }

    async function loadPresets() {
      const response = await fetch("/api/presets");
      const data = await response.json();
      presetSelect.innerHTML = "";
      data.presets.forEach((preset) => {
        addPresetOption(preset, `${preset.index}. ${preset.name}`, preset.index);
      });
      hydratePresetFields();
      const preset = selectedPresetObject();
      if (preset) applyPresetToArticleFields(preset);
    }

    function addPresetOption(preset, label, value) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.dataset.topic = preset.topic || "";
      option.dataset.audience = preset.audience || "";
      option.dataset.tone = preset.tone || "";
      option.dataset.sections = preset.section_count || preset.sections || "";
      option.dataset.aspect = preset.aspect_ratio || "";
      option.dataset.resolution = preset.resolution || "";
      option.dataset.useWebSearch = String(Boolean(preset.use_web_search));
      option.dataset.style = preset.image_style || "";
      option.dataset.preset = JSON.stringify(preset);
      presetSelect.appendChild(option);
      return option;
    }

    function replacePresetOptions(presets, labelPrefix = "") {
      presetSelect.innerHTML = "";
      presets.forEach((preset, index) => {
        const label = `${labelPrefix}${index + 1}. ${preset.name || preset.topic || "未命名灵感"}`;
        addPresetOption(preset, label, dynamicPresetCounter++);
      });
      if (presetSelect.options.length > 0) {
        presetSelect.selectedIndex = 0;
        hydratePresetFields();
        const firstPreset = selectedPresetObject();
        if (firstPreset) applyPresetToArticleFields(firstPreset);
      }
    }

    function hydratePresetFields() {
      const option = presetSelect.selectedOptions[0];
      if (!option) return;
      topicInput.placeholder = option.dataset.topic || "选择或确认灵感后自动填入";
      audienceInput.placeholder = option.dataset.audience || "选择或确认灵感后自动填入";
      toneInput.placeholder = option.dataset.tone || "选择或确认灵感后自动填入";
      sectionsInput.placeholder = option.dataset.sections || "自动";
      aspectInput.placeholder = option.dataset.aspect || "自动";
      resolutionInput.placeholder = option.dataset.resolution || "自动";
      styleInput.placeholder = option.dataset.style || "选择或确认灵感后自动填入";
    }

    function selectedPresetObject() {
      const option = presetSelect.selectedOptions[0];
      if (!option || !option.dataset.preset) return null;
      try {
        return JSON.parse(option.dataset.preset);
      } catch {
        return null;
      }
    }

    function applyPresetToArticleFields(preset) {
      topicInput.value = preset.topic || "";
      audienceInput.value = preset.audience || "";
      toneInput.value = preset.tone || "";
      sectionsInput.value = preset.section_count || preset.sections || "";
      aspectInput.value = preset.aspect_ratio || "";
      resolutionInput.value = preset.resolution || "";
      useWebSearchInput.checked = Boolean(preset.use_web_search);
      styleInput.value = preset.image_style || "";
    }

    function setBusy(isBusy) {
      generateButton.disabled = isBusy;
      statusPill.textContent = isBusy ? "Running" : "Idle";
    }

    function renderJob(job) {
      jobId.textContent = job.job_id || "-";
      jobStatus.textContent = job.status || "-";
      jobStatus.className = job.status === "succeeded" ? "ok" : job.status === "failed" ? "bad" : "warn";
      title.textContent = job.result?.title || "-";
      imageCount.textContent = job.result?.image_count ?? "-";
      logBox.textContent = (job.logs || []).map((item) => `[${item.at}] ${item.message}`).join("\n");
      logBox.scrollTop = logBox.scrollHeight;

      links.innerHTML = "";
      if (job.status === "succeeded" && job.result) {
        message.textContent = job.result.summary || "生成完成。";
        [
          ["打开 HTML", job.result.article_html, "open"],
          ["查看 Markdown", job.result.article_markdown, "open"],
          ["获取 JSON", `/api/jobs/${job.job_id}/result`, "download"],
        ].forEach(([label, href, icon]) => {
          const link = document.createElement("a");
          link.className = "button-link";
          link.href = href;
          link.target = "_blank";
          link.rel = "noreferrer";
          link.innerHTML = `${iconPath(icon)}${label}`;
          links.appendChild(link);
        });
        if (job.result.article_html) {
          previewFrame.src = job.result.article_html;
          previewFrame.style.display = "block";
          previewHint.style.display = "none";
        }
        setBusy(false);
        if (pollTimer) clearInterval(pollTimer);
      } else if (job.status === "failed") {
        message.textContent = job.error || "生成失败。";
        previewFrame.removeAttribute("src");
        previewFrame.style.display = "none";
        previewHint.style.display = "block";
        previewHint.textContent = "生成失败，暂无可预览页面。";
        setBusy(false);
        if (pollTimer) clearInterval(pollTimer);
      } else {
        message.textContent = "任务正在运行，页面会自动刷新状态。";
        previewFrame.removeAttribute("src");
        previewFrame.style.display = "none";
        previewHint.style.display = "block";
        previewHint.textContent = "任务进行中，完成后会自动显示预览。";
        setBusy(true);
      }
    }

    async function pollJob(id) {
      const response = await fetch(`/api/jobs/${id}`);
      const job = await response.json();
      renderJob(job);
    }

    async function createJob() {
      const preset = selectedPresetObject();
      const numericPresetIndex = Number(presetSelect.value);
      const payload = Number.isFinite(numericPresetIndex) && numericPresetIndex < 1000
        ? { preset_index: numericPresetIndex }
        : { preset };
      if (topicInput.value.trim()) payload.topic = topicInput.value.trim();
      if (audienceInput.value.trim()) payload.audience = audienceInput.value.trim();
      if (toneInput.value.trim()) payload.tone = toneInput.value.trim();
      if (sectionsInput.value.trim()) payload.sections = Number(sectionsInput.value);
      if (aspectInput.value.trim()) payload.aspect_ratio = aspectInput.value.trim();
      if (resolutionInput.value.trim()) payload.resolution = resolutionInput.value.trim();
      if (storageModeInput.value.trim()) payload.storage_mode = storageModeInput.value.trim();
      if (generationProfileInput.value.trim()) payload.generation_profile = generationProfileInput.value.trim();
      payload.use_web_search = useWebSearchInput.checked;
      if (styleInput.value.trim()) payload.image_style = styleInput.value.trim();

      setBusy(true);
      message.textContent = "任务已提交，等待生成进度。";
      const response = await fetch("/api/articles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const job = await response.json();
      if (!response.ok) {
        setBusy(false);
        message.textContent = job.error || "提交失败。";
        return;
      }
      renderJob(job);
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(() => pollJob(job.job_id), 2500);
      pollJob(job.job_id);
    }

    async function generatePresetIdeas() {
      const selectedPreset = selectedPresetObject();
      const brief = presetBriefInput.value.trim()
        || topicInput.value.trim()
        || selectedPreset?.topic
        || "适合微信公众号传播的 AI 主题文章灵感";
      generatePresetsButton.disabled = true;
      message.textContent = "正在换一批灵感。";
      const payload = {
        brief,
        count: Number(presetCountInput.value || 3)
      };
      if (presetAspectInput.value.trim()) payload.aspect_ratio = presetAspectInput.value.trim();
      const response = await fetch("/api/presets/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      generatePresetsButton.disabled = false;
      if (!response.ok) {
        message.textContent = data.error || "换一批灵感失败。";
        return;
      }
      replacePresetOptions(data.presets || [], "灵感 ");
      message.textContent = `已换成 ${(data.presets || []).length} 个新灵感，文章参数已同步为第一条。`;
    }

    async function completePresetIdea() {
      const payload = {};
      if (completeIdeaInput.value.trim()) payload.idea = completeIdeaInput.value.trim();
      if (!payload.idea) {
        message.textContent = "请输入指定创意。";
        return;
      }
      completePresetButton.disabled = true;
      message.textContent = "正在确认指定创意。";
      const response = await fetch("/api/presets/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      completePresetButton.disabled = false;
      if (!response.ok) {
        message.textContent = data.error || "确认指定创意失败。";
        return;
      }
      replacePresetOptions([data.preset], "指定 ");
      message.textContent = "指定创意已确认，文章参数已同步。";
    }

    presetSelect.addEventListener("change", () => {
      hydratePresetFields();
      const preset = selectedPresetObject();
      if (preset) applyPresetToArticleFields(preset);
    });
    generateButton.addEventListener("click", createJob);
    generatePresetsButton.addEventListener("click", generatePresetIdeas);
    completePresetButton.addEventListener("click", completePresetIdea);
    loadPresets().catch((error) => {
      message.textContent = `加载预设失败：${error}`;
    });

    fetch("/api/jobs")
      .then((response) => response.json())
      .then((data) => {
        if (data.jobs && data.jobs.length > 0) renderJob(data.jobs[0]);
      })
      .catch(() => {});
  </script>
</body>
</html>
"""


DOCS_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grok WeChat Article Studio</title>
  <style>
    :root {
      --bg: #f5f7f4;
      --surface: #ffffff;
      --ink: #17211c;
      --muted: #5f6d66;
      --line: #d9e0dc;
      --accent: #0e7c66;
      --accent-strong: #0a6b5b;
      --accent-soft: #e3f0eb;
      --good: #0e7c66;
      --warn: #cc8800;
      --bad: #c9302c;
      --code-bg: #101b17;
      --code-ink: #d7eee4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif;
      letter-spacing: 0;
      line-height: 1.6;
    }
    .shell { max-width: 1440px; margin: 0 auto; padding: 20px 16px; }
    header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 20px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--line);
      margin-bottom: 20px;
    }
    h1 { margin: 0; font-size: 28px; font-weight: 700; }
    h2 { margin: 0 0 12px; font-size: 16px; font-weight: 600; }
    h3 { margin: 0 0 10px; font-size: 14px; font-weight: 600; }
    h4 { margin: 8px 0; font-size: 13px; font-weight: 600; }
    p { margin: 0; color: var(--muted); }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* 流程进度条 */
    .process-bar {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      padding: 20px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 20px;
    }
    .step {
      display: flex;
      flex-direction: column;
      align-items: center;
      position: relative;
    }
    .step-dot {
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: #f0f4f1;
      border: 2px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      color: var(--muted);
      font-size: 16px;
      transition: all 0.3s ease;
      margin-bottom: 8px;
    }
    .step.active .step-dot {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }
    .step.done .step-dot {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }
    .step-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--ink);
      text-align: center;
      margin-bottom: 4px;
    }
    .step-time {
      font-size: 11px;
      color: var(--muted);
    }

    /* 主布局 */
    main {
      display: grid;
      grid-template-columns: 380px 1fr;
      gap: 20px;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    .panel-section {
      margin-bottom: 20px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--line);
    }
    .panel-section:last-child {
      border-bottom: none;
      margin-bottom: 0;
      padding-bottom: 0;
    }

    /* 表单元素 */
    label {
      display: block;
      margin-top: 10px;
      font-size: 12px;
      color: var(--muted);
      font-weight: 600;
    }
    label:first-child { margin-top: 0; }
    input, select, textarea {
      width: 100%;
      margin-top: 6px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfa;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
    }
    textarea {
      resize: vertical;
      min-height: 80px;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
      background: #fff;
    }

    /* 按钮 */
    button {
      width: 100%;
      padding: 10px 14px;
      margin-top: 10px;
      border: none;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: all 0.2s ease;
    }
    button.primary {
      background: var(--accent);
      color: white;
    }
    button.primary:hover {
      background: var(--accent-strong);
    }
    button.secondary {
      background: var(--accent-soft);
      color: var(--accent-strong);
      border: 1px solid #cfe1da;
    }
    button.secondary:hover {
      background: #d9e9e3;
    }
    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    /* 网格和行 */
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }

    /* 右侧内容区 */
    .content-area {
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    /* Tab 面板 */
    .tabs {
      display: flex;
      gap: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .tab-button {
      flex: 1;
      padding: 12px 14px;
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--muted);
      font-weight: 600;
      cursor: pointer;
      text-align: center;
      margin: 0;
      border-radius: 0;
    }
    .tab-button.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
      background: #fbfcfa;
    }
    .tab-content {
      padding: 18px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 0 0 8px 8px;
      border-top: none;
      margin-top: -1px;
      display: none;
    }
    .tab-content.active {
      display: block;
    }

    /* 指标卡片 */
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 16px;
    }
    .metric {
      background: #fbfcfa;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
    }
    .metric-label {
      font-size: 11px;
      color: var(--muted);
      font-weight: 600;
      margin-bottom: 6px;
    }
    .metric-value {
      font-size: 18px;
      font-weight: 700;
      color: var(--ink);
      word-break: break-all;
    }

    /* 预设卡片 */
    .presets-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 12px;
    }
    .preset-card {
      border: 2px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      cursor: pointer;
      transition: all 0.2s;
      background: #fbfcfa;
    }
    .preset-card:hover {
      border-color: var(--accent);
    }
    .preset-card.selected {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    .preset-card-name {
      font-weight: 600;
      font-size: 13px;
      margin-bottom: 8px;
    }
    .preset-card-info {
      font-size: 11px;
      color: var(--muted);
      line-height: 1.5;
    }

    /* Draft 预览 */
    .draft-preview {
      background: #fbfcfa;
      padding: 16px;
      border-radius: 6px;
      max-height: 400px;
      overflow-y: auto;
    }
    .draft-title {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .draft-subtitle {
      font-size: 14px;
      color: var(--muted);
      margin-bottom: 12px;
    }
    .draft-summary {
      font-size: 12px;
      color: var(--muted);
      font-style: italic;
      padding: 10px;
      background: white;
      border-left: 3px solid var(--accent);
      margin-bottom: 12px;
      border-radius: 4px;
    }
    .draft-section {
      margin-bottom: 14px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--line);
    }
    .draft-section:last-child {
      border-bottom: none;
    }
    .draft-section h4 {
      margin-bottom: 6px;
    }
    .draft-section p {
      margin: 4px 0;
      font-size: 12px;
    }
    .draft-section ul {
      margin: 6px 0;
      padding-left: 18px;
    }
    .draft-section li {
      font-size: 12px;
      margin: 2px 0;
    }
    .draft-stats {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin-top: 12px;
    }

    /* 日志 */
    .log {
      background: #111c18;
      color: #d7eee4;
      padding: 12px;
      border-radius: 6px;
      font-family: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
      font-size: 11px;
      line-height: 1.5;
      max-height: 300px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .log-line { margin: 2px 0; }

    /* 工具栏 */
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }
    .toolbar button {
      flex: 1;
      min-width: 120px;
      margin: 0;
      padding: 8px 12px;
      font-size: 12px;
    }

    /* 响应式 */
    @media (max-width: 1024px) {
      main { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(2, 1fr); }
    }
    @media (max-width: 640px) {
      header { display: block; }
      .process-bar { grid-template-columns: repeat(2, 1fr); }
      .row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>✨ Grok WeChat Article Studio</h1>
        <p style="margin-top: 4px;">AI 驱动的公众号文章生成系统 — <a href="/docs" target="_blank">查看 API 文档</a></p>
      </div>
      <div style="font-size: 18px; font-weight: 700; color: var(--muted);" id="statusBadge">准备就绪</div>
    </header>

    <!-- 流程进度条 -->
    <div class="process-bar" id="processBar" style="display: none;">
      <div class="step active" id="step1">
        <div class="step-dot">1</div>
        <div class="step-label">预设生成</div>
        <div class="step-time" id="step1Time"></div>
      </div>
      <div class="step" id="step2">
        <div class="step-dot">2</div>
        <div class="step-label">文章草稿</div>
        <div class="step-time" id="step2Time"></div>
      </div>
      <div class="step" id="step3">
        <div class="step-dot">3</div>
        <div class="step-label">图片生成</div>
        <div class="step-time" id="step3Time"></div>
      </div>
      <div class="step" id="step4">
        <div class="step-dot">4</div>
        <div class="step-label">完成</div>
        <div class="step-time" id="step4Time"></div>
      </div>
    </div>

    <!-- 主体布局 -->
    <main>
      <!-- 左侧：配置面板 -->
      <div class="panel">
        <h2>生成配置</h2>

        <div class="panel-section">
          <h3>灵感池</h3>
          <label>当前灵感</label>
          <select id="preset"></select>

          <label for="presetBrief">换一批方向</label>
          <textarea id="presetBrief" placeholder="例如：面向家长的AI教育公众号选题"></textarea>

          <label style="margin-top: 10px;">数量</label>
          <input id="presetCount" type="number" min="1" max="10" value="5" placeholder="1-10">

          <button class="secondary" id="generatePresets" type="button">
            <span>🔄 换一批灵感</span>
          </button>
        </div>

        <div class="panel-section">
          <h3>指定创意</h3>
          <label for="completeIdea">创意描述</label>
          <textarea id="completeIdea" placeholder="例如：未来生活方式想象"></textarea>
          <button class="secondary" id="completePreset" type="button">
            <span>✓ 完成创意</span>
          </button>
        </div>

        <div class="panel-section">
          <h3>文章设定</h3>
          <label for="topic">主题</label>
          <textarea id="topic" placeholder="自动填入或编辑"></textarea>

          <label for="audience">目标读者</label>
          <textarea id="audience" placeholder="自动填入或编辑"></textarea>

          <label for="tone">语气</label>
          <input id="tone" placeholder="自动填入或编辑">

          <div class="row">
            <div>
              <label for="sections">小节数</label>
              <input id="sections" type="number" min="1" max="8" placeholder="3-4">
            </div>
            <div>
              <label for="aspect">图片比例</label>
              <select id="aspect">
                <option value="">自动</option>
                <option value="16:9">16:9</option>
                <option value="4:3">4:3</option>
                <option value="1:1">1:1</option>
              </select>
            </div>
          </div>

          <div class="row">
            <div>
              <label for="resolution">清晰度</label>
              <select id="resolution">
                <option value="">自动</option>
                <option value="1k">1K</option>
                <option value="2k">2K</option>
              </select>
            </div>
            <div>
              <label for="storageMode">存储模式</label>
              <select id="storageMode">
                <option value="local">本地预览</option>
                <option value="remote">自动远程（优先R2）</option>
                <option value="r2">上传R2</option>
                <option value="oss">上传OSS</option>
              </select>
            </div>
            <div>
              <label for="generationProfile">生成策略</label>
              <select id="generationProfile">
                <option value="speed">速度优先</option>
                <option value="balanced" selected>均衡</option>
                <option value="quality">质量优先</option>
              </select>
            </div>
          </div>

          <label class="checkbox">
            <input id="useWebSearch" type="checkbox">
            <span style="color: var(--ink); margin-left: 4px;">联网补充事实</span>
          </label>

          <label for="style">视觉风格</label>
          <textarea id="style" placeholder="自动填入或编辑"></textarea>
        </div>

        <button class="primary" id="generate" type="button">
          <span>▶️ 开始生成</span>
        </button>
      </div>

      <!-- 右侧：内容区 -->
      <div class="content-area">
        <!-- 预设和草稿的Tab页 -->
        <div>
          <div class="tabs">
            <button class="tab-button active" data-tab="result">任务结果</button>
            <button class="tab-button" data-tab="presets">预设对比</button>
            <button class="tab-button" data-tab="draft">文章草稿</button>
            <button class="tab-button" data-tab="logs">运行日志</button>
          </div>

          <!-- Tab: 任务结果 -->
          <div class="tab-content active" id="result-tab">
            <div class="metrics">
              <div class="metric">
                <div class="metric-label">任务 ID</div>
                <div class="metric-value" id="jobId" style="font-size: 12px;">-</div>
              </div>
              <div class="metric">
                <div class="metric-label">状态</div>
                <div class="metric-value" id="jobStatus" style="font-size: 13px;">-</div>
              </div>
              <div class="metric">
                <div class="metric-label">标题</div>
                <div class="metric-value" id="title" style="font-size: 12px;">-</div>
              </div>
              <div class="metric">
                <div class="metric-label">图片数</div>
                <div class="metric-value" id="imageCount">-</div>
              </div>
            </div>

            <div id="message" class="empty" style="text-align: center; padding: 40px 20px;">
              👈 选择灵感，点击"开始生成"
            </div>

            <div id="links" class="toolbar" style="display: none;"></div>
          </div>

          <!-- Tab: 预设对比 -->
          <div class="tab-content" id="presets-tab">
            <div id="presetsList" class="presets-list"></div>
            <div id="presetsEmpty" class="empty">暂无预设数据</div>
          </div>

          <!-- Tab: 文章草稿 -->
          <div class="tab-content" id="draft-tab">
            <div id="draftContent" class="draft-preview"></div>
            <div id="draftEmpty" class="empty">草稿生成后在这里显示</div>
          </div>

          <!-- Tab: 运行日志 -->
          <div class="tab-content" id="logs-tab">
            <div id="log" class="log"></div>
          </div>
        </div>

        <!-- 页面预览 -->
        <div class="panel">
          <h2>页面预览</h2>
          <div id="previewHint" class="empty">生成完成后自动预览</div>
          <iframe
            id="previewFrame"
            style="display:none;width:100%;min-height:600px;border:1px solid var(--line);border-radius:6px;background:#fff;"
          ></iframe>
        </div>
      </div>
    </main>
  </div>

  <script>
    // ===== 状态管理 =====
    const state = {
      presets: [],
      draft: null,
      currentPresetIndex: null,
      jobId: null,
      pollTimer: null,
      stepTimings: { 1: null, 2: null, 3: null, 4: null },
      startTime: null
    };

    // ===== 元素引用 =====
    const els = {
      preset: document.getElementById("preset"),
      topic: document.getElementById("topic"),
      audience: document.getElementById("audience"),
      tone: document.getElementById("tone"),
      sections: document.getElementById("sections"),
      aspect: document.getElementById("aspect"),
      resolution: document.getElementById("resolution"),
      storageMode: document.getElementById("storageMode"),
      generationProfile: document.getElementById("generationProfile"),
      useWebSearch: document.getElementById("useWebSearch"),
      style: document.getElementById("style"),
      presetBrief: document.getElementById("presetBrief"),
      presetCount: document.getElementById("presetCount"),
      completeIdea: document.getElementById("completeIdea"),
      generatePresets: document.getElementById("generatePresets"),
      completePreset: document.getElementById("completePreset"),
      generate: document.getElementById("generate"),
      statusBadge: document.getElementById("statusBadge"),
      processBar: document.getElementById("processBar"),
      jobId: document.getElementById("jobId"),
      jobStatus: document.getElementById("jobStatus"),
      title: document.getElementById("title"),
      imageCount: document.getElementById("imageCount"),
      links: document.getElementById("links"),
      message: document.getElementById("message"),
      log: document.getElementById("log"),
      previewHint: document.getElementById("previewHint"),
      previewFrame: document.getElementById("previewFrame"),
      presetsList: document.getElementById("presetsList"),
      draftContent: document.getElementById("draftContent"),
      tabButtons: document.querySelectorAll(".tab-button"),
      tabContents: document.querySelectorAll(".tab-content")
    };

    // ===== 事件绑定 =====
    els.generatePresets.addEventListener("click", handleGeneratePresets);
    els.completePreset.addEventListener("click", handleCompletePreset);
    els.generate.addEventListener("click", handleGenerate);
    els.preset.addEventListener("change", handlePresetChange);
    els.tabButtons.forEach(btn => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    // ===== Tab 切换 =====
    function switchTab(tabName) {
      els.tabButtons.forEach(btn => btn.classList.toggle("active", btn.dataset.tab === tabName));
      els.tabContents.forEach(content => content.classList.toggle("active", content.id === tabName + "-tab"));
    }

    // ===== 状态更新 =====
    function updateStatus(text) {
      els.statusBadge.textContent = text;
    }

    function updateProcessStep(step) {
      if (step >= 1 && step <= 4) {
        for (let i = 1; i <= 4; i++) {
          const stepEl = document.getElementById(`step${i}`);
          stepEl.classList.toggle("active", i === step);
          stepEl.classList.toggle("done", i < step);
        }
      }
    }

    // ===== 预设处理 =====
    async function handleGeneratePresets() {
      const brief = els.presetBrief.value.trim();
      if (!brief) {
        alert("请输入创意简报");
        return;
      }
      els.generatePresets.disabled = true;
      updateStatus("生成预设中...");
      try {
        const res = await fetch("/api/presets/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brief, count: parseInt(els.presetCount.value) || 5 })
        });
        const data = await res.json();
        if (data.presets) {
          displayPresets(data.presets);
          switchTab("presets");
        }
      } catch (err) {
        alert("生成预设失败: " + err.message);
      } finally {
        els.generatePresets.disabled = false;
        updateStatus("准备就绪");
      }
    }

    function displayPresets(presets) {
      state.presets = presets;
      els.presetsList.innerHTML = presets.map((p, i) => `
        <div class="preset-card" data-index="${i}">
          <div class="preset-card-name">${p.name}</div>
          <div class="preset-card-info">
            <div><b>主题：</b>${p.topic}</div>
            <div style="margin-top: 4px;"><b>读者：</b>${p.audience}</div>
            <div style="margin-top: 4px;"><b>语气：</b>${p.tone}</div>
          </div>
        </div>
      `).join("");

      els.presetsList.querySelectorAll(".preset-card").forEach((card, i) => {
        card.addEventListener("click", () => selectPreset(i));
      });
    }

    function selectPreset(index) {
      const preset = state.presets[index];
      if (!preset) return;
      els.presetsList.querySelectorAll(".preset-card").forEach((card, i) => {
        card.classList.toggle("selected", i === index);
      });
      applyPreset(preset);
    }

    function applyPreset(preset) {
      els.topic.value = preset.topic || "";
      els.audience.value = preset.audience || "";
      els.tone.value = preset.tone || "";
      els.sections.value = preset.section_count || "";
      els.aspect.value = preset.aspect_ratio || "";
      els.resolution.value = preset.resolution || "";
      els.useWebSearch.checked = !!preset.use_web_search;
      els.style.value = preset.image_style || "";
    }

    async function handleCompletePreset() {
      const idea = els.completeIdea.value.trim();
      if (!idea) {
        alert("请输入创意描述");
        return;
      }
      els.completePreset.disabled = true;
      updateStatus("完成创意中...");
      try {
        const res = await fetch("/api/presets/complete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ idea })
        });
        const data = await res.json();
        if (data.preset) {
          applyPreset(data.preset);
          alert("创意已自动补全");
        }
      } catch (err) {
        alert("完成创意失败: " + err.message);
      } finally {
        els.completePreset.disabled = false;
        updateStatus("准备就绪");
      }
    }

    // ===== 文章生成 =====
    async function handleGenerate() {
      if (!els.topic.value.trim()) {
        alert("请先填入主题");
        return;
      }

      els.generate.disabled = true;
      state.jobId = null;
      state.stepTimings = { 1: null, 2: null, 3: null, 4: null };
      state.startTime = Date.now();
      els.processBar.style.display = "grid";
      updateStatus("生成中...");
      updateProcessStep(1);

      try {
        const payload = {
          topic: els.topic.value,
          audience: els.audience.value,
          tone: els.tone.value,
          sections: parseInt(els.sections.value) || undefined,
          aspect_ratio: els.aspect.value || undefined,
          resolution: els.resolution.value || undefined,
          storage_mode: els.storageMode.value,
          generation_profile: els.generationProfile.value,
          use_web_search: els.useWebSearch.checked,
          image_style: els.style.value
        };

        const res = await fetch("/api/articles", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        const job = await res.json();
        if (job.job_id) {
          state.jobId = job.job_id;
          els.jobId.textContent = job.job_id;
          els.log.textContent = "";
          els.message.style.display = "none";
          els.links.style.display = "none";
          switchTab("logs");
          pollStatus();
        } else {
          alert("创建任务失败");
        }
      } catch (err) {
        alert("生成失败: " + err.message);
      } finally {
        els.generate.disabled = false;
      }
    }

    // ===== 轮询状态 =====
    function pollStatus() {
      if (!state.jobId) return;

      fetch(`/api/jobs/${state.jobId}`)
        .then(r => r.json())
        .then(job => {
          updateJobUI(job);

          if (job.status === "succeeded" || job.status === "failed") {
            clearTimeout(state.pollTimer);
            els.generate.disabled = false;
            updateStatus("完成");
          } else {
            state.pollTimer = setTimeout(pollStatus, 1000);
          }
        });
    }

    function updateJobUI(job) {
      els.jobStatus.textContent = job.status;
      els.jobStatus.style.color = job.status === "succeeded" ? "var(--good)" : job.status === "failed" ? "var(--bad)" : "var(--warn)";

      if (job.result) {
        els.title.textContent = job.result.title || "-";
        els.imageCount.textContent = job.result.image_count || "-";

        const links = [];
        if (job.result.article_html) links.push(["📄 打开HTML", job.result.article_html, "open"]);
        if (job.result.article_markdown) links.push(["📝 查看Markdown", job.result.article_markdown, "open"]);
        if (job.result.article_json) links.push(["📦 下载JSON", job.result.article_json, "download"]);

        els.links.innerHTML = links.map(([label, url, action]) => `
          <button class="secondary" onclick="window.open('${url}', '_blank')">
            ${label}
          </button>
        `).join("");
        els.links.style.display = "flex";

        if (job.result.article_html) {
          els.previewFrame.src = job.result.article_html;
          els.previewFrame.style.display = "block";
          els.previewHint.style.display = "none";
        }
      }

      if (job.draft) {
        displayDraft(job.draft);
        updateProcessStep(2);
      }

      if (job.logs) {
        els.log.textContent = job.logs.map((log, i) => {
          const timestamp = new Date().toLocaleTimeString();
          return `[${timestamp}] ${log}`;
        }).join("\n");
        els.log.scrollTop = els.log.scrollHeight;
      }
    }

    function displayDraft(draft) {
      if (!draft) return;
      const html = `
        <div class="draft-title">${draft.title || ""}</div>
        <div class="draft-subtitle">${draft.subtitle || ""}</div>
        <div class="draft-summary">${draft.summary || ""}</div>
        ${(draft.sections || []).map(section => `
          <div class="draft-section">
            <h4>${section.heading}</h4>
            <p><strong>${section.hook}</strong></p>
            ${(section.paragraphs || []).map(p => `<p>${p}</p>`).join("")}
            <ul>${(section.bullets || []).map(b => `<li>${b}</li>`).join("")}</ul>
          </div>
        `).join("")}
      `;
      els.draftContent.innerHTML = html;
    }

    // ===== 初始化 =====
    async function loadPresets() {
      try {
        const res = await fetch("/api/presets");
        const data = await res.json();
        els.preset.innerHTML = (data.presets || []).map((p, i) => `
          <option value="${i}">${p.index}. ${p.name}</option>
        `).join("");
        if (data.presets.length > 0) {
          handlePresetChange();
        }
      } catch (err) {
        console.error("Failed to load presets:", err);
      }
    }

    function handlePresetChange() {
      const index = parseInt(els.preset.value);
      if (index >= 0) {
        // 根据需要应用preset
      }
    }

    loadPresets();
  </script>
</body>
</html>
"""


# ===== 新 UI（深色模态风格）=====
NEW_UI_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>✨ AI 文章创意工作室</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      background: linear-gradient(135deg, #0f172e 0%, #1a1f35 100%);
      color: #e0e6ed;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif;
      min-height: 100vh;
      overflow-x: hidden;
    }

    .container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 20px;
    }

    header {
      background: rgba(20, 28, 50, 0.8);
      backdrop-filter: blur(10px);
      padding: 20px 0;
      margin-bottom: 40px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      position: sticky;
      top: 0;
      z-index: 100;
    }

    header .inner {
      max-width: 1400px;
      margin: 0 auto;
      padding: 0 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    h1 {
      font-size: 24px;
      font-weight: 700;
      background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }

    .status-badge {
      padding: 8px 16px;
      background: rgba(99, 102, 241, 0.2);
      border: 1px solid rgba(99, 102, 241, 0.5);
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      color: #a5b4fc;
    }

    main {
      display: grid;
      grid-template-columns: 400px 1fr;
      gap: 30px;
    }

    .config-panel {
      background: rgba(20, 28, 50, 0.5);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 30px;
      height: fit-content;
      position: sticky;
      top: 100px;
    }

    .config-panel h2 {
      font-size: 18px;
      margin-bottom: 20px;
      color: #fff;
    }

    .form-group {
      margin-bottom: 20px;
    }

    .form-group label {
      display: block;
      margin-bottom: 8px;
      font-size: 13px;
      font-weight: 600;
      color: #a0aec0;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .form-group input,
    .form-group textarea,
    .form-group select {
      width: 100%;
      padding: 12px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      color: #e0e6ed;
      font-family: inherit;
      font-size: 13px;
      transition: all 0.2s;
    }

    .form-group input:focus,
    .form-group textarea:focus,
    .form-group select:focus {
      outline: none;
      background: rgba(255, 255, 255, 0.1);
      border-color: #6366f1;
      box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
    }

    .form-group textarea {
      resize: vertical;
      min-height: 80px;
    }

    button {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      width: 100%;
      padding: 12px 16px;
      background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
      color: white;
      border: none;
      border-radius: 8px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.2s;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    button:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 20px rgba(99, 102, 241, 0.3);
    }

    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .btn-secondary {
      background: rgba(255, 255, 255, 0.1);
      color: #a5b4fc;
    }

    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.15);
    }

    .content-area {
      display: flex;
      flex-direction: column;
      gap: 30px;
    }

    .card {
      background: rgba(20, 28, 50, 0.5);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 30px;
    }

    .card h2 {
      font-size: 18px;
      margin-bottom: 20px;
      color: #fff;
    }

    .modal {
      display: none !important;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    .modal-content {
      background: rgba(20, 28, 50, 0.95);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 16px;
      padding: 40px;
      max-width: 90%;
      width: 1000px;
      max-height: 90vh;
      overflow-y: auto;
      animation: slideUp 0.3s;
    }

    @keyframes slideUp {
      from {
        opacity: 0;
        transform: translateY(20px);
      }
      to {
        opacity: 0;
        transform: translateY(0);
      }
    }

    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 30px;
      padding-bottom: 20px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }

    .modal-header h2 {
      margin: 0;
      font-size: 24px;
    }

    .modal-close {
      background: none;
      border: none;
      color: #a0aec0;
      font-size: 28px;
      cursor: pointer;
      padding: 0;
      width: auto;
      transition: color 0.2s;
    }

    .modal-close:hover {
      color: #e0e6ed;
    }

    .presets-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .preset-card {
      background: rgba(255, 255, 255, 0.05);
      border: 2px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 16px;
      cursor: pointer;
      transition: all 0.2s;
    }

    .preset-card:hover {
      border-color: #6366f1;
      background: rgba(99, 102, 241, 0.1);
    }

    .preset-card.selected {
      border-color: #6366f1;
      background: rgba(99, 102, 241, 0.2);
      box-shadow: 0 0 20px rgba(99, 102, 241, 0.2);
    }

    .preset-card-name {
      font-size: 15px;
      font-weight: 700;
      margin-bottom: 12px;
      color: #fff;
      min-height: 20px;
    }

    .preset-card-info {
      font-size: 12px;
      color: #a0aec0;
      line-height: 1.8;
    }

    .preset-card-info div {
      margin-bottom: 8px;
      word-break: break-word;
      display: block;
    }

    .preset-card-info strong {
      color: #cbd5e1;
      display: inline;
      min-width: 60px;
    }

    .metrics {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 15px;
      margin-bottom: 20px;
    }

    .metric {
      background: rgba(255, 255, 255, 0.05);
      padding: 15px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.1);
    }

    .metric-label {
      font-size: 11px;
      color: #a0aec0;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }

    .metric-value {
      font-size: 16px;
      font-weight: 700;
      color: #e0e6ed;
      word-break: break-all;
    }

    .log-box {
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      padding: 15px;
      font-family: "SF Mono", Monaco, "Cascadia Code", monospace;
      font-size: 12px;
      color: #6ee7b7;
      max-height: 300px;
      overflow-y: auto;
      line-height: 1.6;
    }

    .log-line {
      margin-bottom: 4px;
    }

    .empty-state {
      text-align: center;
      padding: 60px 20px;
      color: #a0aec0;
    }

    .preview-frame {
      width: 100%;
      height: 600px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      background: white;
    }

    .tab-btn {
      background: transparent;
      border: none;
      color: #a0aec0;
      cursor: pointer;
      padding: 10px 0;
      font-size: 13px;
      font-weight: 600;
      border-bottom: 2px solid transparent;
      transition: all 0.2s;
      margin-bottom: -15px;
      padding-bottom: 15px;
    }

    .tab-btn:hover {
      color: #e0e6ed;
    }

    .tab-btn.active {
      color: #6366f1;
      border-bottom-color: #6366f1;
    }

    .tab-content {
      animation: fadeIn 0.2s;
    }

    .tab-content.active {
      display: block;
    }

    @media (max-width: 1200px) {
      main {
        grid-template-columns: 1fr;
      }
      .config-panel {
        position: static;
      }
      .metrics {
        grid-template-columns: repeat(2, 1fr);
      }
    }

    @media (max-width: 768px) {
      .metrics {
        grid-template-columns: 1fr;
      }
      .presets-list {
        max-height: 400px;
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="inner">
      <h1>✨ AI 文章创意工作室</h1>
      <div class="status-badge" id="statusBadge">准备就绪</div>
    </div>
  </header>

  <div class="container">
    <main>
      <div class="config-panel">
        <h2>📝 生成配置</h2>

        <button class="btn-secondary" id="generatePresetsBtn" style="margin-bottom: 25px;">
          🔄 获取灵感预设
        </button>

        <div style="margin: 25px 0; padding: 20px 0; border-top: 1px solid rgba(255,255,255,0.1); border-bottom: 1px solid rgba(255,255,255,0.1);">
          <div class="form-group">
            <label>或输入创意描述</label>
            <textarea id="ideaInput" placeholder="例如：AI如何改变工作方式"></textarea>
          </div>
          <button class="btn-secondary" id="completePresetBtn">
            ✓ 完成创意
          </button>
        </div>

        <div class="form-group">
          <label>主题</label>
          <textarea id="topicInput" placeholder="自动填入"></textarea>
        </div>

        <div class="form-group">
          <label>目标读者</label>
          <textarea id="audienceInput" placeholder="自动填入"></textarea>
        </div>

        <div class="form-group">
          <label>语气风格</label>
          <textarea id="toneInput" placeholder="自动填入"></textarea>
        </div>

        <div class="form-group">
          <label>小节数</label>
          <input id="sectionsInput" type="number" min="1" max="8" placeholder="3-4">
        </div>

        <div class="form-group">
          <label>图片风格</label>
          <textarea id="styleInput" placeholder="自动填入"></textarea>
        </div>

        <button id="generateBtn" style="margin-top: 20px;">
          ▶️ 开始生成文章
        </button>
      </div>

      <div class="content-area">
        <div class="card">
          <h2>📊 生成进度</h2>
          <div class="metrics">
            <div class="metric">
              <div class="metric-label">任务ID</div>
              <div class="metric-value" id="jobIdMetric">-</div>
            </div>
            <div class="metric">
              <div class="metric-label">状态</div>
              <div class="metric-value" id="statusMetric">-</div>
            </div>
            <div class="metric">
              <div class="metric-label">标题</div>
              <div class="metric-value" id="titleMetric" style="font-size: 13px;">-</div>
            </div>
            <div class="metric">
              <div class="metric-label">图片数</div>
              <div class="metric-value" id="imageCountMetric">-</div>
            </div>
          </div>

          <div id="actionButtons" style="display: none; display: flex; gap: 10px; flex-wrap: wrap;">
            <button class="btn-secondary" id="htmlBtn">📄 HTML</button>
            <button class="btn-secondary" id="mdBtn">📝 Markdown</button>
            <button class="btn-secondary" id="jsonBtn">📦 JSON</button>
          </div>

          <div id="emptyState" class="empty-state">
            <p>等待生成...</p>
          </div>
        </div>

        <div class="card">
          <div style="display: flex; gap: 10px; margin-bottom: 20px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 15px;">
            <button class="tab-btn active" data-tab="presets">🎨 灵感预设</button>
            <button class="tab-btn" data-tab="logs">📋 运行日志</button>
            <button class="tab-btn" data-tab="preview">👁️ 页面预览</button>
          </div>

          <div id="presetsTab" class="tab-content active">
            <div id="presetsLoading" style="text-align: center; padding: 40px; color: #a0aec0;">
              点击上方按钮获取灵感预设
            </div>
            <div id="presetsContainer" style="display: none;">
              <div class="presets-list" id="presetsList" style="max-height: 600px; overflow-y: auto;"></div>
            </div>
          </div>

          <div id="logsTab" class="tab-content" style="display: none;">
            <div class="log-box" id="logBox">
              <div class="log-line" style="color: #a0aec0;">等待开始...</div>
            </div>
          </div>

          <div id="previewTab" class="tab-content" style="display: none;">
            <iframe id="previewFrame" class="preview-frame" title="article preview"></iframe>
          </div>
        </div>
      </div>
    </main>
  </div>

  <script>
    const state = {
      presets: [],
      selectedPresetIndex: null,
      jobId: null,
      pollTimer: null,
      lastLogIndex: 0
    };

    async function init() {
      // No auto-loading of presets. User clicks "获取灵感预设" to generate them.
      updateStatus('准备就绪');
    }

    function applyPreset(preset) {
      document.getElementById('topicInput').value = preset.topic || '';
      document.getElementById('audienceInput').value = preset.audience || '';
      document.getElementById('toneInput').value = preset.tone || '';
      document.getElementById('sectionsInput').value = preset.section_count || preset.sections || '';
      document.getElementById('styleInput').value = preset.image_style || '';
    }

    document.getElementById('generatePresetsBtn').addEventListener('click', async () => {
      updateStatus('生成灵感中...');
      document.getElementById('generatePresetsBtn').disabled = true;
      document.getElementById('presetsLoading').style.display = 'block';
      document.getElementById('presetsContainer').style.display = 'none';

      try {
        const res = await fetch('/api/presets/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ brief: 'AI innovation and digital transformation', count: 6 })
        });

        const data = await res.json();
        if (data.presets) {
          state.presets = data.presets;
          displayPresetsModal(data.presets);
        }
      } catch (err) {
        alert('生成失败: ' + err.message);
      } finally {
        document.getElementById('generatePresetsBtn').disabled = false;
        updateStatus('准备就绪');
      }
    });

    function displayPresetsModal(presets) {
      const list = document.getElementById('presetsList');
      list.innerHTML = presets.map((p, i) => `
        <div class="preset-card" data-index="${i}" onclick="selectPresetCard(${i})">
          <div class="preset-card-name">${p.name}</div>
          <div class="preset-card-info">
            <div><strong>📌 主题:</strong> ${p.topic?.substring(0, 80)}...</div>
            <div><strong>👥 读者:</strong> ${p.audience?.substring(0, 60)}...</div>
            <div><strong>💬 语气:</strong> ${p.tone?.substring(0, 60)}...</div>
            <div><strong>📄 小节:</strong> ${p.section_count}</div>
          </div>
        </div>
      `).join('');

      document.getElementById('presetsLoading').style.display = 'none';
      document.getElementById('presetsContainer').style.display = 'block';

      // Switch to presets tab
      switchTab('presets');
    }

    function selectPresetCard(index) {
      // Apply preset immediately
      applyPreset(state.presets[index]);

      // Highlight selected card
      document.querySelectorAll('.preset-card').forEach((card, i) => {
        card.classList.toggle('selected', i === index);
      });
    }

    function switchTab(tabName) {
      // Hide all tabs
      document.querySelectorAll('.tab-content').forEach(el => {
        el.classList.remove('active');
        el.style.display = 'none';
      });

      // Remove active state from all buttons
      document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
      });

      // Show selected tab
      const tabEl = document.getElementById(tabName + 'Tab');
      if (tabEl) {
        tabEl.classList.add('active');
        tabEl.style.display = 'block';
      }

      // Activate button
      document.querySelector(`[data-tab="${tabName}"]`)?.classList.add('active');
    }

    document.getElementById('completePresetBtn').addEventListener('click', async () => {
      const idea = document.getElementById('ideaInput').value.trim();
      if (!idea) {
        alert('请输入创意描述');
        return;
      }

      updateStatus('完成创意中...');
      document.getElementById('completePresetBtn').disabled = true;

      try {
        const res = await fetch('/api/presets/complete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ idea })
        });

        const data = await res.json();
        if (data.preset) {
          applyPreset(data.preset);
          document.getElementById('ideaInput').value = '';
          alert('✓ 创意已自动补全');
        }
      } catch (err) {
        alert('完成失败: ' + err.message);
      } finally {
        document.getElementById('completePresetBtn').disabled = false;
        updateStatus('准备就绪');
      }
    });

    document.getElementById('generateBtn').addEventListener('click', async () => {
      const topic = document.getElementById('topicInput').value.trim();
      if (!topic) {
        alert('请输入主题');
        return;
      }

      state.jobId = null;
      updateStatus('生成中...');
      clearLogs();
      logMessage('📌 任务已创建，开始生成...');

      document.getElementById('generateBtn').disabled = true;

      try {
        const payload = {
          topic,
          audience: document.getElementById('audienceInput').value,
          tone: document.getElementById('toneInput').value,
          sections: parseInt(document.getElementById('sectionsInput').value) || undefined,
          image_style: document.getElementById('styleInput').value,
          storage_mode: 'remote'
        };

        const res = await fetch('/api/articles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        const job = await res.json();
        if (job.job_id) {
          state.jobId = job.job_id;
          logMessage(`✓ Job ID: ${job.job_id}`);
          pollStatus();
        } else {
          alert('创建任务失败');
        }
      } catch (err) {
        alert('生成失败: ' + err.message);
        updateStatus('准备就绪');
        document.getElementById('generateBtn').disabled = false;
      }
    });

    function pollStatus() {
      if (!state.jobId) return;

      fetch(`/api/jobs/${state.jobId}`)
        .then(r => r.json())
        .then(job => {
          updateJobUI(job);

          if (job.status === 'succeeded') {
            updateStatus('✓ 完成');
            document.getElementById('generateBtn').disabled = false;
            logMessage('✓ 生成完成！');
          } else if (job.status === 'failed') {
            updateStatus('✗ 失败');
            document.getElementById('generateBtn').disabled = false;
            logMessage('✗ 生成失败: ' + (job.error || '未知错误'));
          } else {
            state.pollTimer = setTimeout(pollStatus, 1000);
          }
        })
        .catch(err => {
          logMessage('❌ 轮询失败: ' + err.message);
          state.pollTimer = setTimeout(pollStatus, 2000);
        });
    }

    function updateJobUI(job) {
      document.getElementById('jobIdMetric').textContent = job.job_id?.substring(0, 20) + '...' || '-';
      document.getElementById('statusMetric').textContent = {
        'queued': '排队中',
        'running': '生成中',
        'succeeded': '✓ 成功',
        'failed': '✗ 失败'
      }[job.status] || job.status;

      if (job.result) {
        document.getElementById('titleMetric').textContent = job.result.title?.substring(0, 20) + '...' || '-';
        document.getElementById('imageCountMetric').textContent = job.result.image_count || '-';

        if (job.result.article_html) {
          document.getElementById('previewFrame').src = job.result.article_html;
          document.getElementById('previewCard').style.display = 'block';
        }

        const links = [];
        if (job.result.article_html) links.push(['HTML', job.result.article_html]);
        if (job.result.article_markdown) links.push(['Markdown', job.result.article_markdown]);
        if (job.result.article_json) links.push(['JSON', job.result.article_json]);

        if (links.length > 0) {
          document.getElementById('htmlBtn').onclick = () => window.open(links[0][1], '_blank');
          if (links[1]) document.getElementById('mdBtn').onclick = () => window.open(links[1][1], '_blank');
          if (links[2]) document.getElementById('jsonBtn').onclick = () => window.open(links[2][1], '_blank');
          document.getElementById('actionButtons').style.display = 'flex';
          document.getElementById('emptyState').style.display = 'none';
        }
      }

      if (job.logs && job.logs.length > state.lastLogIndex) {
        // Only add new logs
        for (let i = state.lastLogIndex; i < job.logs.length; i++) {
          const log = job.logs[i];
          const msg = typeof log === 'string' ? log : (log.message || JSON.stringify(log));
          logMessage(msg);
        }
        state.lastLogIndex = job.logs.length;
      }
    }

    function updateStatus(text) {
      document.getElementById('statusBadge').textContent = text;
    }

    function clearLogs() {
      document.getElementById('logBox').innerHTML = '';
      state.lastLogIndex = 0;
    }

    function logMessage(msg) {
      const box = document.getElementById('logBox');
      const line = document.createElement('div');
      line.className = 'log-line';
      line.textContent = msg;
      box.appendChild(line);
      box.scrollTop = box.scrollHeight;
    }

    // Setup tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        switchTab(e.target.getAttribute('data-tab'));
      });
    });

    init();
  </script>
</body>
</html>
"""


FLOW_UI_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>✨ AI 文章创意工坊 - 三步生成</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      min-height: 100vh;
      padding: 40px 20px;
    }

    .container {
      max-width: 1200px;
      margin: 0 auto;
    }

    header {
      text-align: center;
      color: white;
      margin-bottom: 50px;
    }

    header h1 {
      font-size: 36px;
      margin-bottom: 10px;
    }

    header p {
      font-size: 16px;
      opacity: 0.9;
    }

    /* 三步进度条 */
    .steps-progress {
      display: flex;
      justify-content: space-between;
      margin-bottom: 60px;
      position: relative;
    }

    .steps-progress::before {
      content: '';
      position: absolute;
      top: 30px;
      left: 0;
      right: 0;
      height: 2px;
      background: rgba(255,255,255,0.3);
      z-index: 0;
    }

    .step {
      flex: 1;
      text-align: center;
      position: relative;
      z-index: 1;
    }

    .step-circle {
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: rgba(255,255,255,0.2);
      border: 3px solid white;
      margin: 0 auto 15px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      transition: all 0.3s ease;
    }

    .step.active .step-circle {
      background: white;
      color: #667eea;
      transform: scale(1.1);
    }

    .step.completed .step-circle {
      background: #4ade80;
    }

    .step-label {
      color: white;
      font-weight: 600;
      font-size: 14px;
    }

    /* 主面板 */
    .main-panel {
      background: white;
      border-radius: 12px;
      padding: 40px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.3);
      min-height: 400px;
    }

    .step-content {
      display: none;
    }

    .step-content.active {
      display: block;
      animation: fadeIn 0.3s ease;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    /* 步骤1: 灵感输入 */
    .inspire-section h2 {
      font-size: 24px;
      margin-bottom: 20px;
      color: #333;
    }

    .inspire-section p {
      color: #666;
      margin-bottom: 20px;
      font-size: 14px;
    }

    textarea {
      width: 100%;
      min-height: 150px;
      padding: 15px;
      border: 2px solid #e5e7eb;
      border-radius: 8px;
      font-size: 14px;
      font-family: inherit;
      resize: vertical;
    }

    textarea:focus {
      outline: none;
      border-color: #667eea;
      box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
    }

    /* 步骤2: 参数确认 */
    .confirm-section h2 {
      font-size: 24px;
      margin-bottom: 30px;
      color: #333;
    }

    .params-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 20px;
      margin-bottom: 30px;
    }

    .param-item {
      display: flex;
      flex-direction: column;
    }

    .param-item label {
      font-weight: 600;
      color: #333;
      margin-bottom: 8px;
      font-size: 13px;
    }

    .param-item input,
    .param-item select,
    .param-item textarea {
      padding: 10px 12px;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      font-size: 13px;
      font-family: inherit;
    }

    .param-item textarea {
      min-height: 80px;
      resize: vertical;
    }

    .param-item.full-width {
      grid-column: 1 / -1;
    }

    .key-points-input {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .key-point-item {
      display: flex;
      gap: 10px;
      align-items: center;
    }

    .key-point-item input {
      flex: 1;
      padding: 8px 10px;
      border: 1px solid #e5e7eb;
      border-radius: 4px;
    }

    .key-point-item button {
      padding: 6px 12px;
      background: #ef4444;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }

    .add-point-btn {
      padding: 8px 12px;
      background: #3b82f6;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
      align-self: flex-start;
    }

    /* 步骤3: 生成中 */
    .generating-section h2 {
      font-size: 24px;
      margin-bottom: 30px;
      color: #333;
    }

    .progress-bar {
      width: 100%;
      height: 8px;
      background: #e5e7eb;
      border-radius: 4px;
      overflow: hidden;
      margin-bottom: 15px;
    }

    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, #667eea, #764ba2);
      transition: width 0.3s ease;
    }

    .progress-text {
      text-align: center;
      font-size: 14px;
      color: #666;
      margin-bottom: 20px;
    }

    .logs-container {
      background: #f9fafb;
      border-radius: 6px;
      padding: 15px;
      max-height: 200px;
      overflow-y: auto;
      font-family: 'Courier New', monospace;
      font-size: 12px;
      line-height: 1.6;
      color: #444;
    }

    .log-line {
      padding: 4px 0;
      border-bottom: 1px solid #e5e7eb;
    }

    .log-line:last-child {
      border-bottom: none;
    }

    /* 按钮 */
    .button-group {
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      margin-top: 30px;
    }

    button {
      padding: 12px 24px;
      border: none;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
    }

    button:hover:not(:disabled) {
      transform: translateY(-2px);
    }

    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .btn-primary {
      background: linear-gradient(135deg, #667eea, #764ba2);
      color: white;
    }

    .btn-secondary {
      background: #e5e7eb;
      color: #333;
    }

    .btn-success {
      background: #4ade80;
      color: white;
    }

    .result-link {
      margin-top: 20px;
      padding: 15px;
      background: #ecfdf5;
      border: 1px solid #4ade80;
      border-radius: 6px;
      text-align: center;
    }

    .result-link a {
      color: #16a34a;
      text-decoration: none;
      font-weight: 600;
    }

    .result-link a:hover {
      text-decoration: underline;
    }

    .error-message {
      background: #fee2e2;
      border: 1px solid #ef4444;
      color: #991b1b;
      padding: 15px;
      border-radius: 6px;
      margin-top: 15px;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>✨ AI 文章创意工坊</h1>
      <p>三步快速生成高质量文章 - 灵感 → 参数 → 成品</p>
    </header>

    <div class="steps-progress">
      <div class="step active" data-step="1">
        <div class="step-circle">💡</div>
        <div class="step-label">灵感输入</div>
      </div>
      <div class="step" data-step="2">
        <div class="step-circle">⚙️</div>
        <div class="step-label">参数确认</div>
      </div>
      <div class="step" data-step="3">
        <div class="step-circle">🚀</div>
        <div class="step-label">生成文章</div>
      </div>
    </div>

    <div class="main-panel">
      <!-- 步骤1: 灵感输入 -->
      <div class="step-content active inspire-section">
        <h2>💡 分享你的灵感</h2>
        <p>描述你想写的文章想法，越详细越好。AI 会自动为你生成完整的文章参数。</p>
        <textarea id="ideaInput" placeholder="例如：我想写一篇关于如何学习 Python 的文章，特别是针对初学者，想强调边学边做的重要性..."></textarea>
        <input type="url" id="referenceImageUrl" placeholder="可选：人物/场景参考图 URL，用于保持视觉一致性">
        <div class="button-group">
          <button class="btn-primary" onclick="goToStep(2)">💡 生成参数</button>
        </div>
      </div>

      <!-- 步骤2: 参数确认 -->
      <div class="step-content confirm-section">
        <h2>⚙️ 确认生成参数</h2>
        <p id="loadingText" style="color: #667eea; font-weight: 600; margin-bottom: 20px; display: none;">🤖 AI 正在生成参数中...</p>

        <div class="params-grid">
          <div class="param-item">
            <label>文章主题</label>
            <input type="text" id="paramTopic" placeholder="文章主题">
          </div>
          <div class="param-item">
            <label>目标受众</label>
            <input type="text" id="paramAudience" placeholder="目标读者描述">
          </div>
          <div class="param-item">
            <label>文风</label>
            <input type="text" id="paramTone" placeholder="文章风格">
          </div>
          <div class="param-item">
            <label>章节数</label>
            <input type="number" id="paramSections" min="2" max="8" value="4">
          </div>
          <div class="param-item">
            <label>文章类型</label>
            <select id="paramStoryType">
              <option value="how-to">How-to (如何做...)</option>
              <option value="story">Story (故事类)</option>
              <option value="listicle">Listicle (列表式)</option>
              <option value="analysis">Analysis (分析评论)</option>
              <option value="informative">Informative (信息类)</option>
            </select>
          </div>
          <div class="param-item">
            <label>生成质量</label>
            <select id="paramGenerationProfile">
              <option value="quality">Quality (深度审稿)</option>
              <option value="balanced">Balanced (均衡)</option>
              <option value="speed">Speed (快速)</option>
            </select>
          </div>
          <div class="param-item">
            <label>宽高比</label>
            <select id="paramAspectRatio">
              <option value="16:9">16:9</option>
              <option value="1:1">1:1</option>
              <option value="3:4">3:4</option>
              <option value="9:16">9:16</option>
            </select>
          </div>
          <div class="param-item">
            <label>分辨率</label>
            <select id="paramResolution">
              <option value="2k">2k</option>
              <option value="1k">1k</option>
            </select>
          </div>
          <div class="param-item">
            <label>
              <input type="checkbox" id="paramUseWebSearch">
              联网检索
            </label>
          </div>
          <div class="param-item full-width">
            <label>配图风格</label>
            <input type="text" id="paramImageStyle" placeholder="professional editorial photography, no text overlay">
          </div>
          <div class="param-item full-width">
            <label>参考图 URL</label>
            <input type="url" id="paramReferenceImageUrl" placeholder="人物/场景参考图 URL">
          </div>
          <div class="param-item full-width">
            <label>文章大纲</label>
            <textarea id="paramOutline" placeholder="例如: 1. 背景介绍 2. 核心内容 3. 实践案例 4. 总结建议"></textarea>
          </div>
          <div class="param-item full-width">
            <label>核心要点</label>
            <div class="key-points-input" id="keyPointsContainer">
              <div class="key-point-item">
                <input type="text" class="key-point-input" placeholder="要点 1">
                <button type="button" onclick="removeKeyPoint(this)">删除</button>
              </div>
            </div>
            <button type="button" class="add-point-btn" onclick="addKeyPoint()">+ 添加要点</button>
          </div>
        </div>

        <div class="button-group">
          <button class="btn-secondary" onclick="goToStep(1)">← 返回修改</button>
          <button class="btn-primary" onclick="goToStep(3)">生成文章 →</button>
        </div>
      </div>

      <!-- 步骤3: 生成中 -->
      <div class="step-content generating-section">
        <h2>🚀 文章生成中...</h2>
        <div class="progress-bar">
          <div class="progress-fill" id="progressFill" style="width: 0%"></div>
        </div>
        <div class="progress-text">
          <span id="progressText">准备中...</span>
        </div>
        <div class="logs-container" id="logsContainer"></div>
        <div id="resultArea"></div>
      </div>
    </div>
  </div>

  <script>
    let state = {
      currentStep: 1,
      idea: '',
      params: {},
      jobId: null
    };

    function createKeyPointInput(value = '', placeholder = '新要点') {
      const div = document.createElement('div');
      div.className = 'key-point-item';
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'key-point-input';
      input.placeholder = placeholder;
      input.value = value;
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = '删除';
      button.onclick = function () { removeKeyPoint(button); };
      div.appendChild(input);
      div.appendChild(button);
      return div;
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[ch]));
    }

    function goToStep(stepNum) {
      if (stepNum === 2) {
        const idea = document.getElementById('ideaInput').value.trim();
        if (!idea) {
          alert('请输入你的灵感!');
          return;
        }
        state.idea = idea;
        state.currentStep = 2;
        generateParameters();
      } else if (stepNum === 3) {
        const params = {
          ...state.params,
          topic: document.getElementById('paramTopic').value,
          audience: document.getElementById('paramAudience').value,
          tone: document.getElementById('paramTone').value,
          sections: parseInt(document.getElementById('paramSections').value),
          outline: document.getElementById('paramOutline').value,
          story_type: document.getElementById('paramStoryType').value,
          use_web_search: document.getElementById('paramUseWebSearch').checked,
          image_style: document.getElementById('paramImageStyle').value,
          aspect_ratio: document.getElementById('paramAspectRatio').value,
          resolution: document.getElementById('paramResolution').value,
          generation_profile: document.getElementById('paramGenerationProfile').value,
          reference_image_url: document.getElementById('paramReferenceImageUrl').value.trim(),
          reference_character_profile: state.params.reference_character_profile || '',
          key_points: Array.from(document.querySelectorAll('.key-point-input'))
            .map(el => el.value.trim())
            .filter(v => v),
          storage_mode: 'remote'
        };

        if (!params.topic || !params.outline || params.key_points.length === 0) {
          alert('请填写主题、大纲和至少一个要点!');
          return;
        }

        state.params = params;
        state.currentStep = 3;
        generateArticle();
      } else if (stepNum === 1) {
        state.currentStep = 1;
      }

      updateUI();
    }

    function generateParameters() {
      document.getElementById('loadingText').style.display = 'block';
      const referenceImageUrl = document.getElementById('referenceImageUrl').value.trim();
      const payload = { idea: state.idea };
      if (referenceImageUrl) payload.reference_image_url = referenceImageUrl;

      fetch('/api/presets/expand-idea', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          alert('生成失败: ' + data.error);
          document.getElementById('loadingText').style.display = 'none';
          return;
        }

        state.params = {
          ...data,
          generation_profile: data.generation_profile || 'quality',
          reference_image_url: data.reference_image_url || referenceImageUrl || '',
          reference_character_profile: data.reference_character_profile || ''
        };
        document.getElementById('paramTopic').value = data.topic || '';
        document.getElementById('paramAudience').value = data.audience || '';
        document.getElementById('paramTone').value = data.tone || '';
        document.getElementById('paramSections').value = data.sections || 4;
        document.getElementById('paramOutline').value = data.outline || '';
        document.getElementById('paramStoryType').value = data.story_type || 'informative';
        document.getElementById('paramUseWebSearch').checked = Boolean(data.use_web_search);
        document.getElementById('paramImageStyle').value = data.image_style || 'professional editorial photography, no text overlay';
        document.getElementById('paramAspectRatio').value = data.aspect_ratio || '16:9';
        document.getElementById('paramResolution').value = data.resolution || '2k';
        document.getElementById('paramGenerationProfile').value = state.params.generation_profile;
        document.getElementById('paramReferenceImageUrl').value = state.params.reference_image_url;

        // 设置 key_points
        const container = document.getElementById('keyPointsContainer');
        container.innerHTML = '';
        (data.key_points || []).forEach((point, idx) => {
          container.appendChild(createKeyPointInput(point, `要点 ${idx + 1}`));
        });

        if ((data.key_points || []).length === 0) {
          container.appendChild(createKeyPointInput('', '要点 1'));
        }

        document.getElementById('loadingText').style.display = 'none';
      })
      .catch(err => {
        alert('请求失败: ' + err.message);
        document.getElementById('loadingText').style.display = 'none';
      });
    }

    function generateArticle() {
      fetch('/api/articles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state.params)
      })
      .then(r => r.json())
      .then(data => {
        if (data.error || !data.job_id) {
          document.getElementById('resultArea').innerHTML =
            '<div class="error-message">生成失败: ' + escapeHtml(data.error || '接口没有返回 job_id') + '</div>';
          return;
        }
        state.jobId = data.job_id;
        pollProgress();
      })
      .catch(err => {
        document.getElementById('resultArea').innerHTML = '<div class="error-message">生成失败: ' + escapeHtml(err.message) + '</div>';
      });
    }

    function pollProgress() {
      fetch(`/api/jobs/${state.jobId}`)
        .then(r => r.json())
        .then(job => {
          updateProgress(job);

          if (job.status === 'succeeded') {
            document.getElementById('resultArea').innerHTML = `
              <div class="result-link">
                ✅ 文章生成完成!
                <br><br>
                <a href="/outputs/${state.jobId}/article.html" target="_blank">📄 查看完整文章</a>
              </div>
            `;
          } else if (job.status === 'failed') {
            document.getElementById('resultArea').innerHTML = '<div class="error-message">❌ 生成失败: ' + escapeHtml(job.error || 'Unknown error') + '</div>';
          } else {
            setTimeout(pollProgress, 2000);
          }
        });
    }

    function updateProgress(job) {
      const logs = job.logs || [];
      const logsHtml = logs.map(l => `<div class="log-line">📌 ${escapeHtml(l.message)}</div>`).join('');
      document.getElementById('logsContainer').innerHTML = logsHtml;

      const phaseProgress = {
        queued: 8,
        running: 25,
        reviewing: 45,
        generating_images: 68,
        rendering: 86,
        uploading: 92,
        succeeded: 100
      };
      const percent = phaseProgress[job.status] || Math.min(95, 20 + logs.length * 8);
      document.getElementById('progressFill').style.width = percent + '%';
      document.getElementById('progressText').textContent = `${job.status || 'running'}... (${logs.length} 步)`;
    }

    function addKeyPoint() {
      const container = document.getElementById('keyPointsContainer');
      container.appendChild(createKeyPointInput());
    }

    function removeKeyPoint(btn) {
      btn.parentElement.remove();
    }

    function updateUI() {
      document.querySelectorAll('.step').forEach((el, idx) => {
        el.classList.remove('active', 'completed');
        if (idx + 1 < state.currentStep) {
          el.classList.add('completed');
        } else if (idx + 1 === state.currentStep) {
          el.classList.add('active');
        }
      });

      document.querySelectorAll('.step-content').forEach((el, idx) => {
        el.classList.remove('active');
        if (idx + 1 === state.currentStep) {
          el.classList.add('active');
        }
      });
    }
  </script>
</body>
</html>
"""


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    JOB_STATE_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), GrokWechatHandler)
    print(f"Grok WeChat Article Studio: http://{HOST}:{PORT}", flush=True)
    print("API: POST /api/articles, GET /api/jobs/{job_id}, GET /api/jobs/{job_id}/result", flush=True)
    print(f"新 UI: http://{HOST}:{PORT}/ui", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
