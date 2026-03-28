#!/usr/bin/env python3
"""
mem0 Memory Service - FastAPI HTTP API
Provides unified memory management for all OpenClaw agents.
"""
import os
import time
import json
import asyncio
import logging
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# Set AWS region before any boto3 import
os.environ.setdefault("AWS_REGION", "us-east-1")

from mem0 import Memory
from config import get_mem0_config, SERVICE_HOST, SERVICE_PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mem0-service")

_add_semaphore = asyncio.Semaphore(5)  # max 5 concurrent /memory/add requests

# ─── Audit Log ───
AUDIT_LOG_DIR = Path(__file__).parent / "audit_logs"
AUDIT_LOG_RETAIN_DAYS = 7


def get_audit_log_path() -> Path:
    AUDIT_LOG_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    return AUDIT_LOG_DIR / f"audit-{today}.jsonl"


def cleanup_old_audit_logs():
    if not AUDIT_LOG_DIR.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=AUDIT_LOG_RETAIN_DAYS)
    for f in AUDIT_LOG_DIR.glob("audit-*.jsonl"):
        try:
            date_str = f.stem.replace("audit-", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                f.unlink()
                logger.info(f"Deleted old audit log: {f.name}")
        except Exception:
            pass


# ─── Global mem0 instance ───
memory: Optional[Memory] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize mem0 on startup."""
    global memory
    logger.info("Initializing mem0 Memory instance...")
    config = get_mem0_config()
    memory = Memory.from_config(config)
    logger.info("✅ mem0 Memory ready")
    cleanup_old_audit_logs()
    yield
    logger.info("Shutting down mem0 Memory Service")


app = FastAPI(
    title="mem0 Memory Service",
    description="Unified memory layer for OpenClaw agents, backed by OpenSearch + Bedrock",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def audit_log_middleware(request: Request, call_next):
    start_time = time.time()

    agent_id = "-"
    user_id = "-"
    if request.method == "POST":
        try:
            body_bytes = await request.body()
            if body_bytes:
                body = json.loads(body_bytes)
                agent_id = body.get("agent_id", "-") or "-"
                user_id = body.get("user_id", "-") or "-"

            async def receive():
                return {"type": "http.request", "body": body_bytes}

            request = Request(request.scope, receive)
        except Exception:
            pass

    response = await call_next(request)

    elapsed_ms = int((time.time() - start_time) * 1000)
    client_ip = request.client.host if request.client else "-"

    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "elapsed_ms": elapsed_ms,
        "ip": client_ip,
        "agent_id": agent_id,
        "user_id": user_id,
    }

    try:
        with get_audit_log_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to write audit log: {e}")

    return response


# ─── Request / Response Models ───


class AddMemoryRequest(BaseModel):
    """Add memories from conversation messages or raw text."""
    messages: Optional[List[Dict[str, str]]] = Field(
        None, description="Conversation messages [{role, content}]"
    )
    text: Optional[str] = Field(None, description="Raw text to memorize (alternative to messages)")
    user_id: str = Field(..., description="User identifier (e.g. 'boss')")
    agent_id: Optional[str] = Field(None, description="Agent identifier (e.g. 'dev', 'main')")
    run_id: Optional[str] = Field(None, description="Run/session identifier (e.g. YYYY-MM-DD for short-term memories)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Extra metadata tags")


class SearchMemoryRequest(BaseModel):
    """Search memories by semantic query."""
    query: str = Field(..., description="Natural language query")
    user_id: str = Field(..., description="User identifier")
    agent_id: Optional[str] = Field(None, description="Filter by agent")
    run_id: Optional[str] = Field(None, description="Filter by run")
    top_k: int = Field(10, description="Max results to return", ge=1, le=100)


class CombinedSearchRequest(BaseModel):
    """Combined search: long-term + recent short-term memories."""
    query: str = Field(..., description="Natural language query")
    user_id: str = Field(..., description="User identifier")
    agent_id: Optional[str] = Field(None, description="Filter by agent")
    top_k: int = Field(10, description="Max results to return", ge=1, le=100)
    recent_days: int = Field(7, description="Number of recent days to include in search", ge=1, le=30)


class UpdateMemoryRequest(BaseModel):
    """Update an existing memory."""
    memory_id: str = Field(..., description="Memory ID to update")
    text: str = Field(..., description="New memory text")


class DeleteMemoryRequest(BaseModel):
    """Delete a specific memory."""
    memory_id: str = Field(..., description="Memory ID to delete")


# ─── API Endpoints ───


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "mem0-memory-service"}


@app.post("/memory/add")
async def add_memory(req: AddMemoryRequest):
    """
    Add memories from conversation messages or raw text.
    mem0 will automatically extract, deduplicate, and store key facts.
    Use run_id (e.g. YYYY-MM-DD) for short-term memories.
    """
    if not req.messages and not req.text:
        raise HTTPException(status_code=400, detail="Either 'messages' or 'text' is required")

    kwargs = {"user_id": req.user_id}
    if req.agent_id:
        kwargs["agent_id"] = req.agent_id
    if req.run_id:
        kwargs["run_id"] = req.run_id
    if req.metadata:
        kwargs["metadata"] = req.metadata

    async with _add_semaphore:
        try:
            if req.messages:
                result = memory.add(req.messages, **kwargs)
            else:
                result = memory.add(req.text, **kwargs)
            return {"status": "ok", "result": result}
        except Exception as e:
            logger.error(f"Error adding memory: {e}", exc_info=True)
            if "Parameter validation failed" in str(e) or "float32" in str(e):
                raise HTTPException(status_code=503, detail="Embedding service temporarily unavailable")
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/memory/search")
async def search_memory(req: SearchMemoryRequest):
    """
    Semantic search across stored memories.
    Returns ranked results with scores.
    """
    kwargs = {"user_id": req.user_id, "limit": req.top_k}
    if req.agent_id:
        kwargs["agent_id"] = req.agent_id
    if req.run_id:
        kwargs["run_id"] = req.run_id

    try:
        results = memory.search(req.query, **kwargs)
        return {"status": "ok", "results": results}
    except Exception as e:
        logger.error(f"Error searching memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/memory/search_combined")
async def search_combined(req: CombinedSearchRequest):
    """
    Combined search: long-term memory (no run_id) + recent short-term memory (run_id=recent dates).
    Returns merged and deduplicated results sorted by score.
    """
    from datetime import timezone

    # Beijing time
    tz_beijing = timezone(timedelta(hours=8))
    today = datetime.now(tz_beijing).date()

    all_results = []
    seen_ids = set()

    # 1. Search long-term memories (no run_id)
    kwargs_long = {"user_id": req.user_id, "limit": req.top_k}
    if req.agent_id:
        kwargs_long["agent_id"] = req.agent_id

    try:
        long_results = memory.search(req.query, **kwargs_long)
        # Handle both dict {"results": [...]} and direct list formats
        results_list = long_results.get("results", long_results) if isinstance(long_results, dict) else long_results
        for r in results_list:
            if r.get("id") not in seen_ids:
                r["memory_type"] = "long_term"
                all_results.append(r)
                seen_ids.add(r.get("id"))
    except Exception as e:
        logger.warning(f"Error searching long-term memories: {e}")

    # 2. Search recent N days of short-term memories
    for i in range(req.recent_days):
        day = today - timedelta(days=i)
        run_id = day.strftime("%Y-%m-%d")
        kwargs_short = {"user_id": req.user_id, "limit": req.top_k, "run_id": run_id}
        if req.agent_id:
            kwargs_short["agent_id"] = req.agent_id
        try:
            short_results = memory.search(req.query, **kwargs_short)
            results_list = short_results.get("results", short_results) if isinstance(short_results, dict) else short_results
            for r in results_list:
                if r.get("id") not in seen_ids:
                    r["memory_type"] = "short_term"
                    r["run_id"] = run_id
                    all_results.append(r)
                    seen_ids.add(r.get("id"))
        except Exception:
            pass  # No memories for this day is normal

    # 3. Sort by score
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {"status": "ok", "results": all_results[:req.top_k]}


@app.get("/memory/list")
async def list_memories(
    user_id: str,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 100,
):
    """List all memories for a user, optionally filtered by agent/run."""
    kwargs = {"user_id": user_id}
    if agent_id:
        kwargs["agent_id"] = agent_id
    if run_id:
        kwargs["run_id"] = run_id

    try:
        results = memory.get_all(**kwargs)
        return {"status": "ok", "results": results}
    except Exception as e:
        logger.error(f"Error listing memories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memory/{memory_id}")
async def get_memory(memory_id: str):
    """Get a specific memory by ID."""
    try:
        result = memory.get(memory_id)
        if not result:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"status": "ok", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/memory/update")
async def update_memory(req: UpdateMemoryRequest):
    """Update an existing memory's text."""
    try:
        result = memory.update(req.memory_id, req.text)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"Error updating memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """Delete a specific memory."""
    try:
        memory.delete(memory_id)
        return {"status": "ok", "deleted": memory_id}
    except Exception as e:
        logger.error(f"Error deleting memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memory/reset")
async def reset_memories(user_id: str, agent_id: Optional[str] = None):
    """
    ⚠️ DANGEROUS: Reset (delete all) memories for a user.
    """
    kwargs = {"user_id": user_id}
    if agent_id:
        kwargs["agent_id"] = agent_id

    try:
        memory.reset()
        return {"status": "ok", "message": f"All memories reset for user={user_id}"}
    except Exception as e:
        logger.error(f"Error resetting memories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memory/history/{memory_id}")
async def memory_history(memory_id: str):
    """Get the change history of a specific memory."""
    try:
        result = memory.history(memory_id)
        return {"status": "ok", "history": result}
    except Exception as e:
        logger.error(f"Error getting memory history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=SERVICE_HOST,
        port=SERVICE_PORT,
        log_level="info",
        workers=1,
        limit_concurrency=20,
        timeout_keep_alive=5,
    )
