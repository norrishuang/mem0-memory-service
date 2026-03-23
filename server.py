#!/usr/bin/env python3
"""
mem0 Memory Service - FastAPI HTTP API
Provides unified memory management for all OpenClaw agents.
"""
import os
import logging
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Set AWS region before any boto3 import
os.environ.setdefault("AWS_REGION", "us-east-1")

from mem0 import Memory
from config import get_mem0_config, SERVICE_HOST, SERVICE_PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mem0-service")

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
    yield
    logger.info("Shutting down mem0 Memory Service")


app = FastAPI(
    title="mem0 Memory Service",
    description="Unified memory layer for OpenClaw agents, backed by OpenSearch + Bedrock",
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Request / Response Models ───


class AddMemoryRequest(BaseModel):
    """Add memories from conversation messages or raw text."""
    messages: Optional[List[Dict[str, str]]] = Field(
        None, description="Conversation messages [{role, content}]"
    )
    text: Optional[str] = Field(None, description="Raw text to memorize (alternative to messages)")
    user_id: str = Field(..., description="User identifier (e.g. 'boss')")
    agent_id: Optional[str] = Field(None, description="Agent identifier (e.g. 'dev', 'main')")
    run_id: Optional[str] = Field(None, description="Run/session identifier")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Extra metadata tags")
    expires_at: Optional[str] = Field(None, description="Expiry date in YYYY-MM-DD format. If set, memory is treated as short-term.")
    ttl_days: Optional[int] = Field(None, description="TTL in days from now. Alternative to expires_at.")


class SearchMemoryRequest(BaseModel):
    """Search memories by semantic query."""
    query: str = Field(..., description="Natural language query")
    user_id: str = Field(..., description="User identifier")
    agent_id: Optional[str] = Field(None, description="Filter by agent")
    run_id: Optional[str] = Field(None, description="Filter by run")
    top_k: int = Field(10, description="Max results to return", ge=1, le=100)


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
    """
    if not req.messages and not req.text:
        raise HTTPException(status_code=400, detail="Either 'messages' or 'text' is required")

    kwargs = {"user_id": req.user_id}
    if req.agent_id:
        kwargs["agent_id"] = req.agent_id
    if req.run_id:
        kwargs["run_id"] = req.run_id

    # Handle short-term memory with TTL
    expires_at = None
    if req.ttl_days and not req.expires_at:
        expires_at = (datetime.utcnow() + timedelta(days=req.ttl_days)).strftime("%Y-%m-%d")
    elif req.expires_at:
        expires_at = req.expires_at

    if expires_at:
        metadata = req.metadata or {}
        metadata["expires_at"] = expires_at
        metadata.setdefault("category", "short_term")
        kwargs["metadata"] = metadata
    elif req.metadata:
        kwargs["metadata"] = req.metadata

    try:
        if req.messages:
            result = memory.add(req.messages, **kwargs)
        else:
            result = memory.add(req.text, **kwargs)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"Error adding memory: {e}", exc_info=True)
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


@app.delete("/memory/cleanup/expired")
async def cleanup_expired_memories(user_id: str, agent_id: Optional[str] = None):
    """
    Delete all short-term memories that have passed their expires_at date.
    Returns count of deleted memories.
    """
    kwargs = {"user_id": user_id}
    if agent_id:
        kwargs["agent_id"] = agent_id

    try:
        # Get all memories for this user/agent
        all_memories = memory.get_all(**kwargs)

        # Handle different return formats (list or dict with 'results' key)
        if isinstance(all_memories, dict):
            memories_list = all_memories.get("results", [])
        else:
            memories_list = all_memories

        # Filter for expired memories
        today = datetime.utcnow().strftime("%Y-%m-%d")
        expired_ids = []

        for mem in memories_list:
            metadata = mem.get("metadata")
            if metadata and isinstance(metadata, dict):
                expires_at = metadata.get("expires_at")
                if expires_at and expires_at < today:
                    expired_ids.append(mem["id"])

        # Delete expired memories
        for mem_id in expired_ids:
            memory.delete(mem_id)

        logger.info(f"Cleaned up {len(expired_ids)} expired memories for user={user_id}, agent={agent_id}")
        return {
            "status": "ok",
            "deleted_count": len(expired_ids),
            "deleted_ids": expired_ids
        }
    except Exception as e:
        logger.error(f"Error cleaning up expired memories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SERVICE_HOST, port=SERVICE_PORT, log_level="info")
