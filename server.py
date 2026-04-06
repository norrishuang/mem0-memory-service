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
import concurrent.futures
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Set AWS region before any boto3 import
os.environ.setdefault("AWS_REGION", "us-east-1")

from mem0 import Memory
from config import get_mem0_config, replace_llm_with_tracked, SERVICE_HOST, SERVICE_PORT
from tracked_llm import reset_token_counter, get_token_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mem0-service")

_add_semaphore = asyncio.Semaphore(5)  # max 5 concurrent /memory/add requests

# Fixed-size thread pool for mem0 sync calls — avoids creating a new
# ThreadPoolExecutor on every memory.add() call (which causes thread accumulation
# because each pool's idle threads take ~60s to exit).
# max_workers=4: matches semaphore(5) with a small buffer; mem0 add is I/O bound
# (Bedrock LLM + embedding + S3Vectors), not CPU bound.
_mem0_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="mem0-add"
)

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
    replace_llm_with_tracked(memory)
    logger.info("✅ mem0 Memory ready (with token tracking)")
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
    # Try query params first (for GET/DELETE requests)
    agent_id = request.query_params.get("agent_id") or "-"
    user_id = request.query_params.get("user_id") or "-"
    if request.method == "POST":
        try:
            body_bytes = await request.body()
            if body_bytes:
                body = json.loads(body_bytes)
                agent_id = body.get("agent_id") or agent_id
                user_id = body.get("user_id") or user_id

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
    infer: bool = Field(True, description="Whether mem0 should infer/extract facts (True) or store raw text (False)")


class SearchMemoryRequest(BaseModel):
    """Search memories by semantic query."""
    query: str = Field(..., description="Natural language query")
    user_id: str = Field(..., description="User identifier")
    agent_id: Optional[str] = Field(None, description="Filter by agent")
    run_id: Optional[str] = Field(None, description="Filter by run")
    top_k: int = Field(5, description="Max results to return", ge=1, le=100)
    min_score: float = Field(0.0, description="Minimum relevance score (0.0–1.0); results below this are dropped", ge=0.0, le=1.0)


class CombinedSearchRequest(BaseModel):
    """Combined search: long-term + recent short-term memories."""
    query: str = Field(..., description="Natural language query")
    user_id: str = Field(..., description="User identifier")
    agent_id: Optional[str] = Field(None, description="Filter by agent")
    top_k: int = Field(5, description="Max results to return", ge=1, le=100)
    recent_days: int = Field(3, description="Number of recent days to include in search", ge=1, le=30)
    min_score: float = Field(0.0, description="Minimum relevance score (0.0–1.0); results below this are dropped", ge=0.0, le=1.0)


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
            loop = asyncio.get_event_loop()
            infer = req.infer  # capture for lambda to avoid late binding

            def _add_with_tracking():
                reset_token_counter()
                if req.messages:
                    result = memory.add(req.messages, infer=infer, **kwargs)
                else:
                    result = memory.add(req.text, infer=infer, **kwargs)
                return result, get_token_stats()

            result, token_stats = await loop.run_in_executor(_mem0_executor, _add_with_tracking)

            # Write token usage to audit log
            if token_stats["llm_calls"] > 0:
                token_log = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "type": "token_usage",
                    "path": "/memory/add",
                    "agent_id": req.agent_id or "-",
                    "user_id": req.user_id,
                    "llm_calls": token_stats["llm_calls"],
                    "input_tokens": token_stats["input_tokens"],
                    "output_tokens": token_stats["output_tokens"],
                    "total_tokens": token_stats["total_tokens"],
                }
                try:
                    with get_audit_log_path().open("a", encoding="utf-8") as f:
                        f.write(json.dumps(token_log, ensure_ascii=False) + "\n")
                except Exception:
                    pass

            return {"status": "ok", "result": result, "token_usage": token_stats}
        except Exception as e:
            err_str = str(e)
            # event=NONE is normal: mem0's LLM decided no update needed, but
            # the internal update API rejects NONE — harmless, not a real error.
            if '"event": "NONE"' in err_str or ("NONE" in err_str and "Parameter validation failed" in err_str):
                logger.warning(f"Ignored event=NONE from mem0 (no action needed): {err_str}")
                return {"status": "ok", "result": {"results": [], "relations": []}, "note": "event=NONE skipped"}
            logger.error(f"Error adding memory: {e}", exc_info=True)
            if "Parameter validation failed" in err_str or "float32" in err_str:
                raise HTTPException(status_code=503, detail="Embedding service temporarily unavailable")
            raise HTTPException(status_code=500, detail=err_str)


def _extract_results(raw):
    """Extract results list from mem0 search response (dict or list)."""
    if isinstance(raw, dict):
        return raw.get("results", [])
    return raw or []


def _search_shared(query: str, agent_id: str = None, top_k: int = 10, run_id: str = None):
    """Search memories with user_id='shared'. Returns a list of result dicts."""
    kwargs = {"user_id": "shared", "limit": top_k}
    if agent_id:
        kwargs["agent_id"] = agent_id
    if run_id:
        kwargs["run_id"] = run_id
    return _extract_results(memory.search(query, **kwargs))


def _merge_results(primary: list, shared: list, seen_ids: set = None):
    """Merge and deduplicate two result lists by id, sorted by score descending."""
    if seen_ids is None:
        seen_ids = {r.get("id") for r in primary}
    merged = list(primary)
    for r in shared:
        if r.get("id") not in seen_ids:
            r["memory_type"] = r.get("memory_type", "shared")
            merged.append(r)
            seen_ids.add(r.get("id"))
    merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    return merged


@app.post("/memory/search")
async def search_memory(req: SearchMemoryRequest):
    """
    Semantic search across stored memories.
    Returns ranked results with scores.
    Also includes user_id='shared' memories (cross-agent experience) when the
    requesting user_id is not already 'shared'.
    """
    kwargs = {"user_id": req.user_id, "limit": req.top_k}
    if req.agent_id:
        kwargs["agent_id"] = req.agent_id
    if req.run_id:
        kwargs["run_id"] = req.run_id

    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            _mem0_executor, lambda: memory.search(req.query, **kwargs)
        )
        raw = _extract_results(results)

        # Include shared memories if user_id is not already "shared"
        if req.user_id != "shared":
            shared = await loop.run_in_executor(
                _mem0_executor, lambda: _search_shared(req.query, req.agent_id, req.top_k, req.run_id)
            )
            raw = _merge_results(raw, shared)

        if req.min_score > 0.0:
            raw = [r for r in raw if r.get("score", 0.0) >= req.min_score]
        return {"status": "ok", "results": {"results": raw}}
    except Exception as e:
        logger.error(f"Error searching memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/memory/search_combined")
async def search_combined(req: CombinedSearchRequest):
    """
    Combined search: long-term memory (no run_id) + recent short-term memory (run_id=recent dates).
    Also includes user_id='shared' memories (cross-agent experience) when the
    requesting user_id is not already 'shared'.
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
        for r in _extract_results(long_results):
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
            for r in _extract_results(short_results):
                if r.get("id") not in seen_ids:
                    r["memory_type"] = "short_term"
                    r["run_id"] = run_id
                    all_results.append(r)
                    seen_ids.add(r.get("id"))
        except Exception:
            pass  # No memories for this day is normal

    # 3. Include shared memories if user_id is not already "shared"
    if req.user_id != "shared":
        try:
            shared = _search_shared(req.query, req.agent_id, req.top_k)
            for r in shared:
                if r.get("id") not in seen_ids:
                    r["memory_type"] = "shared"
                    all_results.append(r)
                    seen_ids.add(r.get("id"))
        except Exception as e:
            logger.warning(f"Error searching shared memories: {e}")

    # 4. Sort by score, apply min_score filter, then cap at top_k
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    if req.min_score > 0.0:
        all_results = [r for r in all_results if r.get("score", 0.0) >= req.min_score]

    return {"status": "ok", "results": all_results[:req.top_k]}


@app.get("/memory/list")
async def list_memories(
    user_id: str,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List all memories for a user, optionally filtered by agent/run."""
    kwargs = {"user_id": user_id}
    if agent_id:
        kwargs["agent_id"] = agent_id
    if run_id:
        kwargs["run_id"] = run_id

    try:
        loop = asyncio.get_event_loop()
        kw = dict(kwargs)
        kw["limit"] = 10000  # override mem0 default limit=100 to fetch all memories (#83)
        all_results = await loop.run_in_executor(_mem0_executor, lambda: memory.get_all(**kw))
        # Normalize: get_all may return dict with "results" key or a list
        if isinstance(all_results, dict) and "results" in all_results:
            items = all_results["results"]
        else:
            items = all_results if isinstance(all_results, list) else []
        total = len(items)
        results = items[offset:offset + limit]
        return {"status": "ok", "results": results, "total": total}
    except Exception as e:
        logger.error(f"Error listing memories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memory/{memory_id}")
async def get_memory(memory_id: str):
    """Get a specific memory by ID."""
    try:
        loop = asyncio.get_event_loop()
        mid = memory_id
        result = await loop.run_in_executor(_mem0_executor, lambda: memory.get(mid))
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
        loop = asyncio.get_event_loop()
        mid, txt = req.memory_id, req.text
        result = await loop.run_in_executor(_mem0_executor, lambda: memory.update(mid, txt))
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"Error updating memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """Delete a specific memory."""
    try:
        loop = asyncio.get_event_loop()
        mid = memory_id
        await loop.run_in_executor(_mem0_executor, lambda: memory.delete(mid))
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
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_mem0_executor, lambda: memory.reset())
        return {"status": "ok", "message": f"All memories reset for user={user_id}"}
    except Exception as e:
        logger.error(f"Error resetting memories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memory/history/{memory_id}")
async def memory_history(memory_id: str):
    """Get the change history of a specific memory."""
    try:
        loop = asyncio.get_event_loop()
        mid = memory_id
        result = await loop.run_in_executor(_mem0_executor, lambda: memory.history(mid))
        return {"status": "ok", "history": result}
    except Exception as e:
        logger.error(f"Error getting memory history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/ui", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="ui")

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
