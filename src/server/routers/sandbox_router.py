"""Sandbox management router — /v1/sandbox/...

Endpoints:
    POST   /v1/sandbox/create                 Create a new ephemeral sandbox
    GET    /v1/sandbox/{sandbox_id}/status    Poll creation status
    POST   /v1/sandbox/{sandbox_id}/agent/stream  SSE: DeepAgent chat
    POST   /v1/sandbox/{sandbox_id}/publish   Publish changed files → destroy sandbox
    DELETE /v1/sandbox/{sandbox_id}           Force-destroy without publishing
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.common.utils import get_logger, secrets
from src.server.services import sandbox_service

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/sandbox", tags=["sandbox"])


# ── Request / Response models ─────────────────────────────────────────────────


class CreateSandboxResponse(BaseModel):
    """Returned immediately on POST /create (sandbox still being provisioned)."""
    sandbox_id: str
    name: str
    status: str  # "creating"


class SandboxStatusResponse(BaseModel):
    """Returned by GET /{id}/status."""
    sandbox_id: str
    name: str
    status: str                   # "creating" | "ready" | "error"
    vscode_url: str
    error_msg: str | None = None
    work_dir: str
    daytona_sandbox_id: str = ""  # Actual Daytona sandbox ID (for TypeScript SDK)
    terminal_url: str = ""        # Daytona web terminal URL (port 22222)


class AgentQueryRequest(BaseModel):
    """Body for POST /{id}/agent/stream."""
    query: str


class PublishResponse(BaseModel):
    """Returned by POST /{id}/publish."""
    published_files: list[str]
    count: int
    sandbox_destroyed: bool = True


class DeleteResponse(BaseModel):
    """Returned by DELETE /{id}."""
    ok: bool



# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_keys() -> tuple[str, str]:
    """Read API keys from secret config.

    Returns:
        (daytona_api_key, openai_api_key)

    Raises:
        HTTPException 500 if a key is missing.
    """
    daytona_key = secrets.get("daytona.api_key")
    openai_key = secrets.get("openai.api_key")

    missing = []
    if not daytona_key:
        missing.append("daytona.api_key")
    if not openai_key:
        missing.append("openai.api_key")

    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing required config keys: {', '.join(missing)}",
        )

    return daytona_key, openai_key


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/create", response_model=CreateSandboxResponse)
async def create_sandbox():
    """Provision a new ephemeral sandbox.

    Returns immediately with status ``"creating"``.  Poll
    ``GET /v1/sandbox/{sandbox_id}/status`` every 3 seconds until
    ``status == "ready"``.

    Returns:
        CreateSandboxResponse with sandbox_id, name, and status "creating".

    Raises:
        HTTPException 429 if max concurrent sandboxes reached.
        HTTPException 500 if API keys are not configured.
    """
    daytona_key, openai_key = _get_keys()

    try:
        sandbox_id = sandbox_service.start_creating(daytona_key, openai_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    record = sandbox_service.get_status(sandbox_id)
    return CreateSandboxResponse(
        sandbox_id=sandbox_id,
        name=record.name,
        status=record.status,
    )


@router.get("/{sandbox_id}/status", response_model=SandboxStatusResponse)
async def get_sandbox_status(sandbox_id: str):
    """Poll sandbox creation / health status.

    Args:
        sandbox_id: UUID returned by POST /create.

    Returns:
        SandboxStatusResponse. When ``status == "ready"`` the ``vscode_url``
        field contains the full preview URL for the iframe.

    Raises:
        HTTPException 404 if sandbox_id is not found.
    """
    record = sandbox_service.get_status(sandbox_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    return SandboxStatusResponse(
        sandbox_id=record.sandbox_id,
        name=record.name,
        status=record.status,
        vscode_url=record.vscode_url,
        error_msg=record.error_msg,
        work_dir=record.work_dir,
        daytona_sandbox_id=record.daytona_sandbox_id,
        terminal_url=record.terminal_url,
    )


@router.post("/{sandbox_id}/agent/stream")
async def stream_agent(sandbox_id: str, body: AgentQueryRequest):
    """Stream DeepAgent response tokens via Server-Sent Events.

    The agent has full access to the sandbox filesystem and Python interpreter.
    Tokens are emitted as ``data: {"type": "token", "content": "..."}`` events.
    The stream ends with ``data: {"type": "done"}``.

    Args:
        sandbox_id: UUID of a sandbox in "ready" status.
        body:       JSON body with ``query`` (str).

    Returns:
        StreamingResponse with ``text/event-stream`` media type.

    Raises:
        HTTPException 404 if sandbox not found.
        HTTPException 409 if sandbox is not in "ready" status.
    """
    record = sandbox_service.get_status(sandbox_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")
    if record.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Sandbox not ready (status={record.status}). Wait until status == 'ready'.",
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Yield SSE-formatted token events from the DeepAgent stream."""
        def _fmt(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        try:
            yield _fmt({"type": "connected", "sandbox_id": sandbox_id})

            async for token in sandbox_service.stream_agent(sandbox_id, body.query):
                yield _fmt({"type": "token", "content": token})

            yield _fmt({"type": "done"})

        except (KeyError, RuntimeError) as exc:
            yield _fmt({"type": "error", "error": str(exc)})
            yield _fmt({"type": "done"})

        except Exception as exc:
            logger.error(f"[sandbox/{sandbox_id}] agent stream error: {exc}", exc_info=True)
            yield _fmt({"type": "error", "error": str(exc)})
            yield _fmt({"type": "done"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{sandbox_id}/publish", response_model=PublishResponse)
async def publish_sandbox(sandbox_id: str, mode: str = "all"):
    """Download changed files from sandbox to local repo, then destroy it.

    Uses ``git diff --name-only HEAD`` inside the sandbox to detect edits made
    since the initial commit.  Each changed file is downloaded and written to
    the corresponding path in the local project root.

    Args:
        sandbox_id: UUID of a sandbox in "ready" status.

    Returns:
        PublishResponse with list of published file paths and count.

    Raises:
        HTTPException 404 if sandbox not found.
        HTTPException 409 if sandbox is not in "ready" status.
    """
    record = sandbox_service.get_status(sandbox_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")
    if record.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Sandbox not ready (status={record.status}).",
        )

    try:
        published = await sandbox_service.publish_sandbox(sandbox_id, mode=mode)
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.error(f"[sandbox/{sandbox_id}] publish error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Publish failed: {exc}")

    return PublishResponse(
        published_files=published,
        count=len(published),
        sandbox_destroyed=True,
    )


@router.delete("/{sandbox_id}", response_model=DeleteResponse)
async def delete_sandbox(sandbox_id: str):
    """Force-destroy a sandbox without publishing changes.

    Args:
        sandbox_id: UUID of any sandbox (any status).

    Returns:
        DeleteResponse with ``ok: true``.

    Raises:
        HTTPException 404 if sandbox not found.
    """
    try:
        await sandbox_service.delete_sandbox(sandbox_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")
    except Exception as exc:
        logger.error(f"[sandbox/{sandbox_id}] delete error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")

    return DeleteResponse(ok=True)


# ── Main block ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    """Smoke test: verify all routes are registered."""
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("routers/sandbox_router.py — route smoke test")
    print("=" * 60)

    routes = {r.path: list(r.methods) for r in router.routes}
    expected = [
        "/v1/sandbox/create",
        "/v1/sandbox/{sandbox_id}/status",
        "/v1/sandbox/{sandbox_id}/agent/stream",
        "/v1/sandbox/{sandbox_id}/publish",
        "/v1/sandbox/{sandbox_id}",
    ]
    for path in expected:
        assert path in routes, f"Missing route: {path}"
        print(f"  [OK] {routes[path]} {path}")

    print()
    print("✅ All sandbox routes registered.")
    print("=" * 60)
