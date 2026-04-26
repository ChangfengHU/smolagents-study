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
import threading
import traceback
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import grok_wechat_article as generator


HOST = os.getenv("GROK_WECHAT_HOST", "127.0.0.1")
PORT = int(os.getenv("GROK_WECHAT_PORT", "8765"))
CORS_ALLOW_ORIGIN = os.getenv("GROK_WECHAT_CORS_ALLOW_ORIGIN", "*")
CORS_ALLOW_METHODS = os.getenv("GROK_WECHAT_CORS_ALLOW_METHODS", "GET, POST, HEAD, OPTIONS")
CORS_ALLOW_HEADERS = os.getenv("GROK_WECHAT_CORS_ALLOW_HEADERS", "Content-Type, X-API-Key, Authorization")
CORS_MAX_AGE = os.getenv("GROK_WECHAT_CORS_MAX_AGE", "86400")
OUTPUT_ROOT = generator.PROJECT_ROOT / "examples" / "generated_articles"
JOB_STATE_DIR = OUTPUT_ROOT / "_jobs"
MAX_LOG_LINES = 200
GENERATION_LOCK = threading.Lock()


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
    return json.loads(path.read_text(encoding="utf-8"))


def save_job(job: dict[str, Any]) -> None:
    JOB_STATE_DIR.mkdir(parents=True, exist_ok=True)
    job_path(job["job_id"]).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


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
            if value not in {"local", "remote"}:
                raise ValueError("storage_mode must be either 'local' or 'remote'.")
        options[key] = value
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
    preset = asdict(generator.CreativePreset.from_dict(payload))
    image_style = preset["image_style"].strip()
    if "no text overlay" not in image_style.lower():
        image_style = f"{image_style}, no text overlay"
    preset["image_style"] = image_style
    if preset["resolution"] not in {"1k", "2k"}:
        preset["resolution"] = "2k"
    if preset["aspect_ratio"] not in {"16:9", "4:3", "3:4", "1:1", "9:16"}:
        preset["aspect_ratio"] = "16:9"
    return preset


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

    client = build_xai_client()
    response = client.post_json(
        "/responses",
        {
            "model": client.config.text_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You complete WeChat article creative presets for an article-and-image generation system. "
                        "Return polished Simplified Chinese editorial fields. Keep image_style in English. "
                        "Do not invent live facts. Use practical evergreen framing unless use_web_search is true."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Complete and improve this creative preset. "
                        "Output one JSON object that exactly matches the schema.\n"
                        f"Idea: {idea or ''}\n"
                        f"Partial preset JSON: {json.dumps(partial, ensure_ascii=False)}"
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "creative_preset",
                    "schema": preset_schema(),
                    "strict": True,
                }
            },
        },
    )
    data = json.loads(generator.extract_response_output_text(response))
    return clean_generated_preset(data)


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
    client = build_xai_client(timeout_seconds=240)
    response = client.post_json(
        "/responses",
        {
            "model": client.config.text_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You design diverse WeChat article creative presets for an article-and-image generation system. "
                        "Return polished Simplified Chinese preset names, topics, audiences, and tones. "
                        "Keep image_style in English and include 'no text overlay'. "
                        "Each preset should be specific enough to generate a strong article package."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Generate {count} creative presets from this brief:\n{brief.strip()}\n"
                        f"Optional defaults or constraints: {json.dumps(defaults, ensure_ascii=False)}"
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "creative_preset_list",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["presets"],
                        "properties": {
                            "presets": {
                                "type": "array",
                                "minItems": count,
                                "maxItems": count,
                                "items": preset_schema(),
                            }
                        },
                    },
                    "strict": True,
                }
            },
        },
    )
    data = json.loads(generator.extract_response_output_text(response))
    presets = data.get("presets")
    if not isinstance(presets, list):
        raise ValueError("Model response did not contain presets.")
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
        if path not in {"/api/articles", "/api/presets/complete", "/api/presets/generate"}:
            write_json(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        if not require_api_key(self):
            return
        try:
            payload = parse_json_body(self)
            if path == "/api/articles":
                job = start_generation_job(payload)
                write_json(self, HTTPStatus.ACCEPTED, job)
            elif path == "/api/presets/complete":
                write_json(self, HTTPStatus.OK, {"preset": complete_creative_preset(payload)})
            else:
                write_json(self, HTTPStatus.OK, generate_creative_presets(payload))
        except ValueError as exc:
            write_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except json.JSONDecodeError:
            write_json(self, HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body."})
        except generator.XAIAPIError as exc:
            write_json(self, HTTPStatus.BAD_GATEWAY, {"error": str(exc)})

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
                <option value="remote">remote（上传 OSS 并替换资源地址）</option>
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
  <title>Grok WeChat Article API Docs</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8f5;
      --surface: #ffffff;
      --ink: #17211c;
      --muted: #5f6d66;
      --line: #d9e0dc;
      --accent: #0e7c66;
      --accent-soft: #e3f0eb;
      --code-bg: #101b17;
      --code-ink: #d7eee4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    .shell { max-width: 1080px; margin: 0 auto; padding: 30px 18px 48px; }
    header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; padding-bottom: 22px; border-bottom: 1px solid var(--line); }
    h1 { margin: 0; font-size: 30px; line-height: 1.15; }
    h2 { margin: 28px 0 12px; font-size: 20px; }
    h3 { margin: 0 0 10px; font-size: 16px; }
    p { color: var(--muted); line-height: 1.7; margin: 8px 0 0; }
    a { color: var(--accent); font-weight: 700; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      border-radius: 7px;
      border: 1px solid #cfe1da;
      padding: 9px 13px;
      background: var(--accent-soft);
      color: #095f4f;
      text-decoration: none;
      white-space: nowrap;
    }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-top: 14px;
    }
    .method {
      display: inline-block;
      min-width: 54px;
      border-radius: 6px;
      padding: 4px 8px;
      background: var(--accent-soft);
      color: #095f4f;
      font-size: 12px;
      font-weight: 800;
      text-align: center;
      margin-right: 8px;
    }
    code, pre {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
    }
    code { background: #edf3f0; padding: 2px 5px; border-radius: 5px; color: #143a31; }
    pre {
      margin: 12px 0 0;
      padding: 14px;
      overflow: auto;
      border-radius: 8px;
      background: var(--code-bg);
      color: var(--code-ink);
      line-height: 1.55;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; line-height: 1.55; }
    th { background: #f0f4f1; font-size: 13px; color: #33433c; }
    tr:last-child td { border-bottom: 0; }
    .note { border-left: 4px solid var(--accent); padding: 12px 14px; background: var(--accent-soft); border-radius: 6px; color: #20483e; }
    @media (max-width: 760px) {
      header { display: block; }
      .button { margin-top: 14px; }
      .grid { grid-template-columns: 1fr; }
      table { display: block; overflow-x: auto; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>Grok WeChat Article API Docs</h1>
        <p>通过 HTTP 创建公众号文章生成任务、查询进度，并获取生成后的 Markdown、HTML、JSON 和图片资源。</p>
      </div>
      <a class="button" href="/">返回控制台</a>
    </header>

    <section>
      <h2>基础信息</h2>
      <div class="grid">
        <div class="card">
          <h3>Base URL</h3>
          <pre>http://127.0.0.1:8765</pre>
        </div>
        <div class="card">
          <h3>鉴权</h3>
          <p>默认不启用接口鉴权。设置环境变量 <code>GROK_WECHAT_API_KEY</code> 后，创建任务接口需要请求头 <code>X-API-Key</code>。</p>
        </div>
      </div>
      <p class="note">生成文章和图片通常需要几分钟，所以接口采用任务模式：先创建任务，再轮询任务状态，成功后读取结果。</p>
    </section>

    <section>
      <h2>接口列表</h2>
      <div class="card">
        <h3><span class="method">GET</span>/api/presets</h3>
        <p>获取可用创意预设列表。</p>
        <pre>curl http://127.0.0.1:8765/api/presets</pre>
        <p>请求参数：无。响应字段见下方 <code>Preset</code> 模型。</p>
      </div>

      <div class="card">
        <h3><span class="method">GET</span>/api/presets/raw</h3>
        <p>获取与 <code>grok_wechat_article_presets.json</code> 同结构的原始预设 JSON，适合外部系统直接同步配置。</p>
        <pre>curl http://127.0.0.1:8765/api/presets/raw</pre>
        <p>请求参数：无。成功返回 <code>{"presets": Preset[]}</code>，但不额外追加 <code>index</code> 字段。</p>
      </div>

      <div class="card">
        <h3><span class="method">POST</span>/api/presets/generate</h3>
        <p>根据一句需求动态生成多套创意预设，返回结构可直接作为预设 JSON 使用。</p>
        <pre>curl -X POST http://127.0.0.1:8765/api/presets/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "brief": "面向家长的 AI 教育公众号选题",
    "count": 3,
    "aspect_ratio": "4:3",
    "resolution": "2k"
  }'</pre>
        <p>请求体字段见下方“生成预设请求体”。成功返回 <code>{"presets": Preset[]}</code>。</p>
      </div>

      <div class="card">
        <h3><span class="method">POST</span>/api/presets/complete</h3>
        <p>把用户给的创意、半成品 preset 或少数字段补全成标准 <code>Preset</code>。</p>
        <pre>curl -X POST http://127.0.0.1:8765/api/presets/complete \
  -H 'Content-Type: application/json' \
  -d '{
    "idea": "未来生活方式想象",
    "preset": {
      "topic": "如果 AI 成为每个人的第二大脑，未来生活会发生哪些具体变化"
    }
  }'</pre>
        <p>请求体字段见下方“补全预设请求体”。成功返回 <code>{"preset": Preset}</code>。</p>
      </div>

      <div class="card">
        <h3><span class="method">POST</span>/api/articles</h3>
        <p>创建一个文章生成任务。接口立即返回 <code>job_id</code>，实际生成在后台执行。</p>
        <pre>curl -X POST http://127.0.0.1:8765/api/articles \
  -H 'Content-Type: application/json' \
  -d '{
    "preset_index": 5,
    "topic": "AI 会怎样改变孩子未来十年的学习方式",
    "sections": 4,
    "aspect_ratio": "4:3"
  }'</pre>
        <p>请求体字段见下方“创建任务请求体”。成功返回 HTTP <code>202</code> 和 <code>Job</code> 对象。</p>
      </div>

      <div class="card">
        <h3><span class="method">GET</span>/api/jobs</h3>
        <p>获取历史任务列表，最新任务排在前面。</p>
        <pre>curl http://127.0.0.1:8765/api/jobs</pre>
        <p>请求参数：无。成功返回 <code>{"jobs": Job[]}</code>。</p>
      </div>

      <div class="card">
        <h3><span class="method">GET</span>/api/jobs/{job_id}</h3>
        <p>查询单个任务状态和运行日志。</p>
        <pre>curl http://127.0.0.1:8765/api/jobs/article-20260426-230000-abcd1234</pre>
        <p>路径参数：<code>job_id</code> 是创建任务时返回的任务 ID。成功返回 <code>Job</code> 对象。</p>
      </div>

      <div class="card">
        <h3><span class="method">GET</span>/api/jobs/{job_id}/result</h3>
        <p>任务成功后，获取完整结果 JSON。包含文章草稿、图片信息和可访问链接。</p>
        <pre>curl http://127.0.0.1:8765/api/jobs/article-20260426-230000-abcd1234/result</pre>
        <p>只有任务状态为 <code>succeeded</code> 时可读取。未完成时返回 HTTP <code>409</code>。</p>
      </div>

      <div class="card">
        <h3><span class="method">GET</span>/api/schema</h3>
        <p>获取机器可读的数据结构定义，重点包含 <code>/api/jobs/{job_id}/result</code> 的完整 JSON schema。</p>
        <pre>curl http://127.0.0.1:8765/api/schema</pre>
        <p>请求参数：无。成功返回 <code>{"schemas": {...}}</code>。</p>
      </div>

      <div class="card">
        <h3><span class="method">GET</span>/outputs/{job_id}/article.html</h3>
        <p>直接打开生成后的 HTML 页面。其他文件同理，例如 <code>article.md</code>、<code>article.json</code>、<code>images/cover.png</code>。</p>
        <pre>open http://127.0.0.1:8765/outputs/article-20260426-230000-abcd1234/article.html</pre>
        <p>返回静态文件内容。Markdown、JSON、HTML 均使用 UTF-8 响应头。</p>
      </div>
    </section>

    <section>
      <h2>创建任务请求体</h2>
      <table>
        <thead>
          <tr><th>字段</th><th>类型</th><th>必填</th><th>默认值</th><th>约束</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr><td><code>preset_index</code></td><td>number</td><td>否</td><td><code>5</code></td><td>1 到当前预设数量</td><td>选择使用哪一套创意预设。</td></tr>
          <tr><td><code>topic</code></td><td>string</td><td>否</td><td>预设 topic</td><td>非空字符串</td><td>覆盖预设主题。</td></tr>
          <tr><td><code>audience</code></td><td>string</td><td>否</td><td>预设 audience</td><td>字符串</td><td>目标读者描述。</td></tr>
          <tr><td><code>tone</code></td><td>string</td><td>否</td><td>预设 tone</td><td>字符串</td><td>文章语气和编辑风格。</td></tr>
          <tr><td><code>sections</code></td><td>number</td><td>否</td><td>预设 section_count</td><td>1 到 8</td><td>正文小节数量。会同时影响文章结构和配图数量。</td></tr>
          <tr><td><code>use_web_search</code></td><td>boolean</td><td>否</td><td>预设 use_web_search</td><td><code>true</code> 或 <code>false</code></td><td>是否允许文本模型使用联网搜索。</td></tr>
          <tr><td><code>image_style</code></td><td>string</td><td>否</td><td>预设 image_style</td><td>字符串</td><td>覆盖封面和正文配图的视觉风格，建议英文。</td></tr>
          <tr><td><code>aspect_ratio</code></td><td>string</td><td>否</td><td>预设 aspect_ratio</td><td>例如 <code>16:9</code>、<code>4:3</code></td><td>图片比例。</td></tr>
          <tr><td><code>resolution</code></td><td>string</td><td>否</td><td>预设 resolution</td><td>例如 <code>1k</code>、<code>2k</code></td><td>图片清晰度。</td></tr>
          <tr><td><code>preset</code></td><td>object</td><td>否</td><td>-</td><td><code>Preset</code> 对象</td><td>可以直接传 <code>/api/presets/complete</code> 返回的 preset。服务会自动把 <code>section_count</code> 映射为 <code>sections</code>。</td></tr>
        </tbody>
      </table>
      <div class="card">
        <h3>用补全后的 preset 创建文章</h3>
        <pre>curl -X POST http://127.0.0.1:8765/api/articles \
  -H 'Content-Type: application/json' \
  -d '{
    "preset": {
      "name": "未来生活方式想象",
      "topic": "如果 AI 成为每个人的第二大脑，未来生活会发生哪些具体变化",
      "audience": "喜欢未来趋势、科技生活方式和想象力内容的读者",
      "tone": "画面感强、可读性高、兼具启发与讨论感",
      "section_count": 4,
      "use_web_search": false,
      "image_style": "speculative future lifestyle illustration, cinematic interiors, human-centered technology, no text overlay",
      "aspect_ratio": "16:9",
      "resolution": "2k"
    }
  }'</pre>
      </div>
    </section>

    <section>
      <h2>生成预设请求体</h2>
      <table>
        <thead>
          <tr><th>字段</th><th>类型</th><th>必填</th><th>默认值</th><th>约束</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr><td><code>brief</code></td><td>string</td><td>是</td><td>-</td><td>非空字符串</td><td>创意生成需求，例如“面向家长的 AI 教育公众号选题”。也可用 <code>topic</code> 或 <code>idea</code> 作为别名。</td></tr>
          <tr><td><code>count</code></td><td>number</td><td>否</td><td><code>5</code></td><td>1 到 10</td><td>生成几套预设。</td></tr>
          <tr><td><code>audience</code></td><td>string</td><td>否</td><td>模型自动判断</td><td>字符串</td><td>给模型的目标读者约束。</td></tr>
          <tr><td><code>tone</code></td><td>string</td><td>否</td><td>模型自动判断</td><td>字符串</td><td>给模型的语气约束。</td></tr>
          <tr><td><code>use_web_search</code></td><td>boolean</td><td>否</td><td>模型自动判断</td><td><code>true</code> 或 <code>false</code></td><td>给生成预设时的联网搜索倾向。</td></tr>
          <tr><td><code>image_style</code></td><td>string</td><td>否</td><td>模型自动判断</td><td>字符串</td><td>给模型的图片风格约束。</td></tr>
          <tr><td><code>aspect_ratio</code></td><td>string</td><td>否</td><td>模型自动判断</td><td>例如 <code>16:9</code></td><td>希望生成预设采用的图片比例。</td></tr>
          <tr><td><code>resolution</code></td><td>string</td><td>否</td><td>模型自动判断</td><td>例如 <code>2k</code></td><td>希望生成预设采用的图片清晰度。</td></tr>
        </tbody>
      </table>
    </section>

    <section>
      <h2>补全预设请求体</h2>
      <table>
        <thead>
          <tr><th>字段</th><th>类型</th><th>必填</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr><td><code>idea</code></td><td>string</td><td>否</td><td>用户一句话创意，例如“未来生活方式想象”。当 <code>preset</code> 很少时建议提供。</td></tr>
          <tr><td><code>preset</code></td><td>object</td><td>否</td><td>半成品预设。可以只传 <code>name</code>、<code>topic</code> 等部分字段。</td></tr>
          <tr><td><code>partial</code></td><td>object</td><td>否</td><td><code>preset</code> 的别名。</td></tr>
          <tr><td><code>name</code> 等顶层字段</td><td>mixed</td><td>否</td><td>也可以不包 <code>preset</code>，直接把 preset 字段放在请求体顶层。</td></tr>
        </tbody>
      </table>
      <div class="card">
        <h3>补全请求示例</h3>
        <pre>{
  "idea": "未来生活方式想象",
  "preset": {
    "name": "未来生活方式想象",
    "topic": "如果 AI 成为每个人的第二大脑，未来生活会发生哪些具体变化"
  }
}</pre>
      </div>
      <div class="card">
        <h3>补全响应示例</h3>
        <pre>{
  "preset": {
    "name": "未来生活方式想象",
    "topic": "如果 AI 成为每个人的第二大脑，未来生活会发生哪些具体变化",
    "audience": "喜欢未来趋势、科技生活方式和想象力内容的读者",
    "tone": "画面感强、可读性高、兼具启发与讨论感",
    "section_count": 4,
    "use_web_search": false,
    "image_style": "speculative future lifestyle illustration, cinematic interiors, human-centered technology, no text overlay",
    "aspect_ratio": "16:9",
    "resolution": "2k"
  }
}</pre>
      </div>
    </section>

    <section>
      <h2>响应模型</h2>
      <div class="card">
        <h3>Preset</h3>
        <table>
          <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
          <tbody>
            <tr><td><code>index</code></td><td>number</td><td>1-based 预设序号，创建任务时传入 <code>preset_index</code>。</td></tr>
            <tr><td><code>name</code></td><td>string</td><td>预设名称。</td></tr>
            <tr><td><code>topic</code></td><td>string</td><td>文章主题。</td></tr>
            <tr><td><code>audience</code></td><td>string</td><td>目标读者。</td></tr>
            <tr><td><code>tone</code></td><td>string</td><td>文章语气。</td></tr>
            <tr><td><code>section_count</code></td><td>number</td><td>默认小节数。</td></tr>
            <tr><td><code>use_web_search</code></td><td>boolean</td><td>是否默认启用联网搜索。</td></tr>
            <tr><td><code>image_style</code></td><td>string</td><td>默认图片风格。</td></tr>
            <tr><td><code>aspect_ratio</code></td><td>string</td><td>默认图片比例。</td></tr>
            <tr><td><code>resolution</code></td><td>string</td><td>默认图片清晰度。</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h3>Job</h3>
        <table>
          <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
          <tbody>
            <tr><td><code>job_id</code></td><td>string</td><td>任务 ID，也是输出目录名。</td></tr>
            <tr><td><code>status</code></td><td>string</td><td><code>queued</code>、<code>running</code>、<code>succeeded</code>、<code>failed</code>。</td></tr>
            <tr><td><code>created_at</code></td><td>string</td><td>UTC ISO 时间。</td></tr>
            <tr><td><code>started_at</code></td><td>string | null</td><td>任务开始时间。排队中可能不存在。</td></tr>
            <tr><td><code>finished_at</code></td><td>string | null</td><td>任务结束时间。未结束时可能不存在。</td></tr>
            <tr><td><code>updated_at</code></td><td>string</td><td>任务状态最近更新时间。</td></tr>
            <tr><td><code>request</code></td><td>object</td><td>创建任务时最终采用的请求参数。</td></tr>
            <tr><td><code>result</code></td><td>object | null</td><td>任务成功后出现，字段见 <code>JobResult</code>。</td></tr>
            <tr><td><code>error</code></td><td>string | null</td><td>失败原因。仅失败时有值。</td></tr>
            <tr><td><code>logs</code></td><td>array</td><td>运行日志数组，每项包含 <code>at</code> 和 <code>message</code>。</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h3>JobResult</h3>
        <table>
          <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
          <tbody>
            <tr><td><code>article_html</code></td><td>string</td><td>生成 HTML 的访问路径。</td></tr>
            <tr><td><code>article_markdown</code></td><td>string</td><td>生成 Markdown 的访问路径。</td></tr>
            <tr><td><code>article_json</code></td><td>string</td><td>生成结果 manifest 的访问路径。</td></tr>
            <tr><td><code>draft_markdown</code></td><td>string</td><td>未生图前的文章草稿 Markdown。</td></tr>
            <tr><td><code>draft_json</code></td><td>string</td><td>未生图前的文章草稿 JSON。</td></tr>
            <tr><td><code>output_dir</code></td><td>string</td><td>服务端本地输出目录。</td></tr>
            <tr><td><code>title</code></td><td>string</td><td>生成文章标题。</td></tr>
            <tr><td><code>summary</code></td><td>string</td><td>文章摘要。</td></tr>
            <tr><td><code>tags</code></td><td>string[]</td><td>文章标签。</td></tr>
            <tr><td><code>image_count</code></td><td>number</td><td>图片数量，通常是封面 1 张加正文每节 1 张。</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>完整结果 JSON 结构</h2>
      <p><code>GET /api/jobs/{job_id}/result</code> 直接读取生成的 <code>article.json</code>，并额外追加 <code>links</code> 字段。</p>
      <table>
        <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
        <tbody>
          <tr><td><code>request</code></td><td>object</td><td>本次生成使用的文章请求参数。</td></tr>
          <tr><td><code>draft</code></td><td>object</td><td>文章草稿，包含 <code>title</code>、<code>subtitle</code>、<code>summary</code>、<code>intro_paragraphs</code>、<code>sections</code>、<code>tags</code> 等。</td></tr>
          <tr><td><code>draft.sections[]</code></td><td>array</td><td>每个小节包含 <code>heading</code>、<code>hook</code>、<code>paragraphs</code>、<code>bullets</code>、<code>takeaway</code>、<code>image_prompt</code>、<code>image_alt</code>、<code>image_caption</code>。</td></tr>
          <tr><td><code>cover_image</code></td><td>object</td><td>封面图信息，包含 <code>prompt</code>、<code>source_url</code>、<code>alt_text</code>、<code>caption</code>、<code>local_path</code>。</td></tr>
          <tr><td><code>section_images[]</code></td><td>array</td><td>正文配图信息，字段同 <code>cover_image</code>。</td></tr>
          <tr><td><code>generated_at</code></td><td>string</td><td>生成完成时间，UTC ISO 格式。</td></tr>
          <tr><td><code>links</code></td><td>object</td><td>HTTP 可访问链接，包含 HTML、Markdown、JSON、草稿和输出目录路径。</td></tr>
        </tbody>
      </table>
      <div class="card">
        <h3>ArticleResult 完整 JSON 示例</h3>
        <pre>{
  "request": {
    "topic": "如果 AI 成为每个人的第二大脑，未来生活会发生哪些具体变化",
    "audience": "喜欢未来趋势、科技生活方式和想象力内容的读者",
    "tone": "画面感强、可读性高、兼具启发与讨论感",
    "sections": 4,
    "use_web_search": false,
    "image_style": "speculative future lifestyle illustration, cinematic interiors, human-centered technology, no text overlay",
    "aspect_ratio": "16:9",
    "resolution": "2k"
  },
  "draft": {
    "title": "当 AI 成为第二大脑，生活会怎样被重写",
    "subtitle": "从记忆、决策到陪伴，理解未来生活方式的真实变化",
    "summary": "一段适合公众号摘要区的文章摘要。",
    "cover_image_prompt": "English cover image prompt, no text overlay",
    "cover_image_alt": "封面图中文替代文本",
    "intro_paragraphs": [
      "导语第一段。",
      "导语第二段。"
    ],
    "sections": [
      {
        "heading": "记忆不再只是存在脑海里",
        "hook": "AI 会先改变我们保存和调用信息的方式。",
        "paragraphs": [
          "小节正文第一段。",
          "小节正文第二段。"
        ],
        "bullets": [
          "要点一",
          "要点二",
          "要点三"
        ],
        "takeaway": "本节总结句。",
        "image_prompt": "English section image prompt, no text overlay",
        "image_alt": "正文配图中文替代文本",
        "image_caption": "正文配图说明"
      }
    ],
    "conclusion_title": "真正重要的是重新定义自己",
    "conclusion_paragraphs": [
      "结尾第一段。",
      "结尾第二段。"
    ],
    "call_to_action": "引导读者评论、收藏或转发的话术。",
    "tags": [
      "AI生活方式",
      "未来趋势",
      "第二大脑"
    ]
  },
  "cover_image": {
    "prompt": "English cover image prompt, no text overlay",
    "source_url": "https://...",
    "alt_text": "封面图中文替代文本",
    "caption": "封面图说明",
    "revised_prompt": null,
    "local_path": "cover.png"
  },
  "section_images": [
    {
      "prompt": "English section image prompt, no text overlay",
      "source_url": "https://...",
      "alt_text": "正文配图中文替代文本",
      "caption": "正文配图说明",
      "revised_prompt": null,
      "local_path": "section-01.png"
    }
  ],
  "generated_at": "2026-04-27T00:00:00Z",
  "links": {
    "article_html": "/outputs/article-20260426-230000-abcd1234/article.html",
    "article_markdown": "/outputs/article-20260426-230000-abcd1234/article.md",
    "article_json": "/outputs/article-20260426-230000-abcd1234/article.json",
    "draft_markdown": "/outputs/article-20260426-230000-abcd1234/draft.md",
    "draft_json": "/outputs/article-20260426-230000-abcd1234/draft.json",
    "output_dir": "/Users/huchangfeng/smolagents-study/examples/generated_articles/article-20260426-230000-abcd1234"
  }
}</pre>
      </div>
      <div class="card">
        <h3>ArticleResult 字段说明</h3>
        <table>
          <thead><tr><th>路径</th><th>类型</th><th>是否必有</th><th>说明</th></tr></thead>
          <tbody>
            <tr><td><code>request.topic</code></td><td>string</td><td>是</td><td>生成文章时最终使用的主题。</td></tr>
            <tr><td><code>request.audience</code></td><td>string</td><td>是</td><td>目标读者。</td></tr>
            <tr><td><code>request.tone</code></td><td>string</td><td>是</td><td>文章语气。</td></tr>
            <tr><td><code>request.sections</code></td><td>number</td><td>是</td><td>正文小节数。</td></tr>
            <tr><td><code>request.use_web_search</code></td><td>boolean</td><td>是</td><td>文本生成是否允许联网搜索。</td></tr>
            <tr><td><code>request.image_style</code></td><td>string</td><td>是</td><td>图片生成风格。</td></tr>
            <tr><td><code>request.aspect_ratio</code></td><td>string</td><td>是</td><td>图片比例。</td></tr>
            <tr><td><code>request.resolution</code></td><td>string</td><td>是</td><td>图片清晰度。</td></tr>
            <tr><td><code>draft.title</code></td><td>string</td><td>是</td><td>文章标题。</td></tr>
            <tr><td><code>draft.subtitle</code></td><td>string</td><td>是</td><td>文章副标题。</td></tr>
            <tr><td><code>draft.summary</code></td><td>string</td><td>是</td><td>文章摘要。</td></tr>
            <tr><td><code>draft.cover_image_prompt</code></td><td>string</td><td>是</td><td>封面图英文提示词。</td></tr>
            <tr><td><code>draft.cover_image_alt</code></td><td>string</td><td>是</td><td>封面图 alt 文案。</td></tr>
            <tr><td><code>draft.intro_paragraphs[]</code></td><td>string[]</td><td>是</td><td>导语段落。</td></tr>
            <tr><td><code>draft.sections[]</code></td><td>object[]</td><td>是</td><td>正文小节数组。</td></tr>
            <tr><td><code>draft.sections[].heading</code></td><td>string</td><td>是</td><td>小节标题。</td></tr>
            <tr><td><code>draft.sections[].hook</code></td><td>string</td><td>是</td><td>小节开场钩子。</td></tr>
            <tr><td><code>draft.sections[].paragraphs[]</code></td><td>string[]</td><td>是</td><td>小节正文段落。</td></tr>
            <tr><td><code>draft.sections[].bullets[]</code></td><td>string[]</td><td>是</td><td>小节要点列表。</td></tr>
            <tr><td><code>draft.sections[].takeaway</code></td><td>string</td><td>是</td><td>小节总结句。</td></tr>
            <tr><td><code>draft.sections[].image_prompt</code></td><td>string</td><td>是</td><td>小节配图英文提示词。</td></tr>
            <tr><td><code>draft.sections[].image_alt</code></td><td>string</td><td>是</td><td>小节配图 alt 文案。</td></tr>
            <tr><td><code>draft.sections[].image_caption</code></td><td>string</td><td>是</td><td>小节配图说明。</td></tr>
            <tr><td><code>draft.conclusion_title</code></td><td>string</td><td>是</td><td>结尾标题。</td></tr>
            <tr><td><code>draft.conclusion_paragraphs[]</code></td><td>string[]</td><td>是</td><td>结尾段落。</td></tr>
            <tr><td><code>draft.call_to_action</code></td><td>string</td><td>是</td><td>公众号互动引导。</td></tr>
            <tr><td><code>draft.tags[]</code></td><td>string[]</td><td>是</td><td>文章标签。</td></tr>
            <tr><td><code>cover_image</code></td><td>object</td><td>是</td><td>封面图对象，字段同 <code>GeneratedImage</code>。</td></tr>
            <tr><td><code>section_images[]</code></td><td>object[]</td><td>是</td><td>正文配图数组，顺序对应 <code>draft.sections[]</code>。</td></tr>
            <tr><td><code>*.prompt</code></td><td>string</td><td>是</td><td>图片原始提示词。</td></tr>
            <tr><td><code>*.source_url</code></td><td>string</td><td>是</td><td>xAI 返回的图片远程 URL。</td></tr>
            <tr><td><code>*.alt_text</code></td><td>string</td><td>是</td><td>图片替代文本。</td></tr>
            <tr><td><code>*.caption</code></td><td>string</td><td>是</td><td>图片说明。</td></tr>
            <tr><td><code>*.revised_prompt</code></td><td>string | null</td><td>否</td><td>模型修订后的提示词，接口未返回时为 <code>null</code> 或不存在。</td></tr>
            <tr><td><code>*.local_path</code></td><td>string | null</td><td>否</td><td>本地图片文件名，例如 <code>cover.png</code>。</td></tr>
            <tr><td><code>generated_at</code></td><td>string</td><td>是</td><td>生成完成时间，UTC ISO 格式。</td></tr>
            <tr><td><code>links.article_html</code></td><td>string</td><td>是</td><td>HTML 访问路径。</td></tr>
            <tr><td><code>links.article_markdown</code></td><td>string</td><td>是</td><td>Markdown 访问路径。</td></tr>
            <tr><td><code>links.article_json</code></td><td>string</td><td>是</td><td>原始 manifest JSON 访问路径。</td></tr>
            <tr><td><code>links.draft_markdown</code></td><td>string</td><td>是</td><td>草稿 Markdown 访问路径。</td></tr>
            <tr><td><code>links.draft_json</code></td><td>string</td><td>是</td><td>草稿 JSON 访问路径。</td></tr>
            <tr><td><code>links.output_dir</code></td><td>string</td><td>是</td><td>服务端本地输出目录。</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>错误返回</h2>
      <table>
        <thead><tr><th>HTTP 状态</th><th>场景</th><th>返回示例</th></tr></thead>
        <tbody>
          <tr><td><code>400</code></td><td>JSON 无效、参数类型不对、<code>preset_index</code> 越界。</td><td><code>{"error":"preset_index must be between 1 and 10."}</code></td></tr>
          <tr><td><code>401</code></td><td>启用 <code>GROK_WECHAT_API_KEY</code> 后，缺少或传错 <code>X-API-Key</code>。</td><td><code>{"error":"Missing or invalid X-API-Key header."}</code></td></tr>
          <tr><td><code>404</code></td><td>任务或输出文件不存在。</td><td><code>{"error":"Unknown job: ..."}</code></td></tr>
          <tr><td><code>409</code></td><td>任务还没成功就读取 <code>/result</code>。</td><td><code>{"error":"Job has not succeeded yet.","job":{...}}</code></td></tr>
        </tbody>
      </table>
    </section>

    <section>
      <h2>返回示例</h2>
      <div class="card">
        <h3>创建任务响应</h3>
        <pre>{
  "job_id": "article-20260426-230000-abcd1234",
  "status": "queued",
  "created_at": "2026-04-26T15:00:00Z",
  "request": {
    "preset_index": 5,
    "sections": 4
  },
  "result": null,
  "error": null,
  "logs": []
}</pre>
      </div>
      <div class="card">
        <h3>成功任务响应</h3>
        <pre>{
  "job_id": "article-20260426-230000-abcd1234",
  "status": "succeeded",
  "result": {
    "article_html": "/outputs/article-20260426-230000-abcd1234/article.html",
    "article_markdown": "/outputs/article-20260426-230000-abcd1234/article.md",
    "article_json": "/outputs/article-20260426-230000-abcd1234/article.json",
    "title": "AI如何重塑孩子未来十年的学习路径",
    "image_count": 5
  }
}</pre>
      </div>
    </section>

    <section>
      <h2>状态说明</h2>
      <table>
        <thead>
          <tr><th>状态</th><th>含义</th></tr>
        </thead>
        <tbody>
          <tr><td><code>queued</code></td><td>任务已创建，等待后台线程启动。</td></tr>
          <tr><td><code>running</code></td><td>正在生成文章草稿、图片或输出文件。</td></tr>
          <tr><td><code>succeeded</code></td><td>已生成完整结果，可以读取 <code>/result</code> 或打开 HTML。</td></tr>
          <tr><td><code>failed</code></td><td>任务失败，查看 <code>error</code> 和 <code>logs</code> 字段定位原因。</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    JOB_STATE_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), GrokWechatHandler)
    print(f"Grok WeChat Article Studio: http://{HOST}:{PORT}", flush=True)
    print("API: POST /api/articles, GET /api/jobs/{job_id}, GET /api/jobs/{job_id}/result", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
