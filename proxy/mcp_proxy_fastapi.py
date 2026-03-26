import os
import time
from pathlib import Path
from typing import AsyncIterator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env.proxy")

app = FastAPI()

ALLOWED_PATH = os.getenv("ALLOWED_PATH", "/f117cfad-62c6-44e9-9190-b70c9d2ebf5b")
TARGET_BASE = os.getenv("TARGET_BASE", "http://localhost:5678/mcp")
MCP_SHARED_TOKEN = os.getenv("MCP_SHARED_TOKEN", "")
PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8090"))

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def safe_token_preview(value: str | None) -> str:
    if not value:
        return "None"
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"


def is_authorized(request: Request) -> bool:
    if not MCP_SHARED_TOKEN:
        print("Auth failed: MCP_SHARED_TOKEN is empty")
        return False

    header_token = request.headers.get("x-mcp-token")
    query_token = request.query_params.get("token")

    print(
        "Auth check:",
        f"header_token={safe_token_preview(header_token)}",
        f"query_token={safe_token_preview(query_token)}",
    )

    return (
        header_token == MCP_SHARED_TOKEN
        or query_token == MCP_SHARED_TOKEN
    )


def filter_headers(headers) -> dict[str, str]:
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in HOP_BY_HOP
    }


def build_target_url(full_path: str, query_string: bytes) -> str:
    base = TARGET_BASE.rstrip("/")
    path = full_path if full_path.startswith("/") else f"/{full_path}"
    target_url = f"{base}{path}"

    if query_string:
        target_url = f"{target_url}?{query_string.decode()}"

    return target_url


@app.api_route("/", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(request: Request, path: str = ""):
    full_path = f"/{path}"

    if not full_path.startswith(ALLOWED_PATH):
        return PlainTextResponse("Not found", status_code=404)

    if not is_authorized(request):
        return PlainTextResponse("Unauthorized", status_code=401)

    target_url = build_target_url(full_path, request.scope.get("query_string", b""))
    start_time = time.perf_counter()
    print(f"[START] {request.method} {full_path} -> {target_url}")

    body = await request.body()
    headers = filter_headers(request.headers)
    headers["X-Accel-Buffering"] = "no"
    headers["Cache-Control"] = "no-cache"
    headers["Connection"] = "keep-alive"

    client = httpx.AsyncClient(timeout=None, follow_redirects=False)

    try:
        upstream_request = client.build_request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )
        upstream = await client.send(upstream_request, stream=True)
        headers_time = time.perf_counter()
        print(
            f"[UPSTREAM_HEADERS] status={upstream.status_code} "
            f"elapsed={(headers_time - start_time):.3f}s"
        )
    except Exception as exc:
        await client.aclose()
        print(f"Upstream connection error: {exc}")
        return PlainTextResponse(f"Upstream connection error: {exc}", status_code=502)

    response_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in HOP_BY_HOP
    }
    response_headers["Cache-Control"] = "no-cache"
    response_headers["X-Accel-Buffering"] = "no"
    response_headers["Connection"] = "keep-alive"

    async def stream_upstream() -> AsyncIterator[bytes]:
        first_chunk_logged = False
        try:
            async for chunk in upstream.aiter_bytes():
                if chunk:
                    if not first_chunk_logged:
                        first_chunk_logged = True
                        first_chunk_time = time.perf_counter()
                        print(
                            f"[FIRST_CHUNK] {request.method} {full_path} "
                            f"elapsed={(first_chunk_time - start_time):.3f}s"
                        )
                    yield chunk
        finally:
            end_time = time.perf_counter()
            print(
                f"[END_STREAM] {request.method} {full_path} "
                f"elapsed={(end_time - start_time):.3f}s"
            )
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_upstream(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )