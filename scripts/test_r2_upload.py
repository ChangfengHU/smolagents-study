#!/usr/bin/env python3
"""Upload a small PNG to Cloudflare R2 using S3-compatible SigV4 auth."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
DEFAULT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def signing_key(secret_key: str, date_stamp: str, region: str = "auto", service: str = "s3") -> bytes:
    key_date = hmac.new(f"AWS4{secret_key}".encode(), date_stamp.encode(), hashlib.sha256).digest()
    key_region = hmac.new(key_date, region.encode(), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service.encode(), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def canonical_object_path(bucket: str, key: str) -> str:
    return "/" + quote(bucket.strip("/"), safe="") + "/" + quote(key.lstrip("/"), safe="/")


def signed_headers(
    *,
    method: str,
    endpoint: str,
    bucket: str,
    key: str,
    access_key: str,
    secret_key: str,
    payload: bytes,
    content_type: str | None = None,
) -> tuple[str, dict[str, str]]:
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit("R2_ENDPOINT_URL must be a full URL, for example https://<accountid>.r2.cloudflarestorage.com")

    now = dt.datetime.now(dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()
    object_path = canonical_object_path(bucket, key)
    url = f"{parsed.scheme}://{parsed.netloc}{object_path}"

    headers = {
        "host": parsed.netloc,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if content_type:
        headers["content-type"] = content_type

    signed_header_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in signed_header_names)
    signed_header_string = ";".join(signed_header_names)
    canonical_request = "\n".join(
        [
            method,
            object_path,
            "",
            canonical_headers,
            signed_header_string,
            payload_hash,
        ]
    )

    credential_scope = f"{date_stamp}/auto/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signature = hmac.new(signing_key(secret_key, date_stamp), string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_header_string}, "
        f"Signature={signature}"
    )
    return url, headers


def request_r2(url: str, headers: dict[str, str], *, method: str, data: bytes | None = None) -> int:
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            response.read()
            return response.status
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} failed with HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise SystemExit(f"{method} failed: {error.reason}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a test image to Cloudflare R2.")
    parser.add_argument("--file", type=Path, help="Local image file to upload. Defaults to a generated 1x1 PNG.")
    parser.add_argument("--key", help="Object key. Defaults to codex-r2-test/<timestamp>.png.")
    args = parser.parse_args()

    load_env(Path(".env"))

    endpoint = require_env("R2_ENDPOINT_URL").rstrip("/")
    bucket = require_env("R2_BUCKET_NAME")
    access_key = require_env("R2_ACCESS_KEY_ID")
    secret_key = require_env("R2_SECRET_ACCESS_KEY")

    if args.file:
        payload = args.file.read_bytes()
        key = args.key or args.file.name
        content_type = "image/png" if args.file.suffix.lower() == ".png" else "application/octet-stream"
    else:
        payload = DEFAULT_PNG
        key = args.key or f"codex-r2-test/{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.png"
        content_type = "image/png"

    put_url, put_headers = signed_headers(
        method="PUT",
        endpoint=endpoint,
        bucket=bucket,
        key=key,
        access_key=access_key,
        secret_key=secret_key,
        payload=payload,
        content_type=content_type,
    )
    put_status = request_r2(put_url, put_headers, method="PUT", data=payload)

    head_url, head_headers = signed_headers(
        method="HEAD",
        endpoint=endpoint,
        bucket=bucket,
        key=key,
        access_key=access_key,
        secret_key=secret_key,
        payload=b"",
    )
    head_headers["x-amz-content-sha256"] = EMPTY_SHA256
    head_status = request_r2(head_url, head_headers, method="HEAD")

    print(f"Uploaded: s3://{bucket}/{key}")
    print(f"PUT status: {put_status}")
    print(f"HEAD status: {head_status}")
    print(f"S3 API URL: {put_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
