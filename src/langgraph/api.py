"""FastAPI server for the deterministic LangGraph portfolio manager.

Runs on port 8001 alongside the existing DeepAgents API (port 8000).

Endpoints:
    GET  /                      - API info
    GET  /v1/health             - Basic liveness check
    GET  /v1/health/detailed    - Per-component health check
    POST /v1/query              - Invoke graph, return final response
    POST /v1/query/stream       - SSE stream node-by-node output
    GET  /v1/conversations/{id} - Load conversation history
    GET  /v1/portfolio/status   - Latest portfolio snapshot
    GET  /v1/portfolio/health   - Portfolio risk compliance
    GET  /v1/portfolio/history  - Historical portfolio snapshots
    GET  /v1/agent/state/{id}   - Graph checkpoint state for a thread
    POST /v1/admin/cleanup      - Delete expired threads
    GET  /v1/admin/stats        - Database statistics
    GET  /v1/tools              - List available graph tools
    GET  /v1/ingestion/status   - Data stream, cache, and ETL pipeline status
    POST /v1/ingestion/trigger-etl   - Manually run ETL indicator computation
    POST /v1/ingestion/flush-cache   - Flush in-memory trade cache to DB
"""

import asyncio
import json
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.langgraph.graph import build_graph, _make_initial_state
from src.common.core.thread_context import set_thread_id, reset_thread_id
from src.common.utils import get_logger, config

logger = get_logger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────
_graph = None

background_tasks: Dict[str, Any] = {
    "data_stream": None,
    "cache_flush": None,
}


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown."""
    global _graph

    # =========================================================================
    # STARTUP
    # =========================================================================
    logger.info("=" * 70)
    logger.info("Starting LangGraph Portfolio Manager API (port 8001)...")
    logger.info("=" * 70)

    # 1. Compile LangGraph
    logger.info("Compiling LangGraph...")
    _graph = build_graph()
    logger.info("Graph compiled and ready")

    # 2. Sync watchlist from Alpaca to database
    logger.info("Syncing watchlist from Alpaca...")
    try:
        from src.common.skills.alpaca_portfolio_skills import get_all_watchlist_symbols
        from src.common.dao import AlpacaDAO

        alpaca_symbols = get_all_watchlist_symbols()

        if not alpaca_symbols:
            logger.warning("No watchlists in Alpaca, using config fallback")
            alpaca_symbols = config.get("watchlist", default=["AAPL"])
            logger.info(f"   Fallback watchlist: {alpaca_symbols}")

        if alpaca_symbols:
            dao = AlpacaDAO()
            db_symbols = set(dao.get_watchlist())
            alpaca_symbols_set = set(alpaca_symbols)

            for symbol in alpaca_symbols_set - db_symbols:
                dao.add_to_watchlist(symbol)
                logger.info(f"   Added {symbol} to watchlist")

            dao.close()
            logger.info(f"Watchlist synced: {len(alpaca_symbols)} symbols")
        else:
            logger.warning("No watchlist configured")

    except Exception as e:
        logger.error(f"Watchlist sync failed: {e}")
        logger.warning("   Will use existing database watchlist")

    # 3. Verify ETL configuration
    logger.info("Verifying ETL configuration...")
    try:
        etl_enabled = config.get("etl.enabled", default=True)
        lookback_days = config.get("etl.lookback_days", default=60)

        if etl_enabled:
            logger.info(f"ETL auto-computation ENABLED (lookback: {lookback_days} days)")
        else:
            logger.warning("ETL auto-computation DISABLED")

        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        try:
            indicator_count = dao.fetch_df("SELECT COUNT(*) as cnt FROM computed_indicators")
            count = indicator_count["cnt"].iloc[0] if not indicator_count.empty else 0
            logger.info(f"Current computed indicators in DB: {count:,} rows")
        except Exception:
            logger.warning("computed_indicators table may not exist yet")
        finally:
            dao.close()
    except Exception as e:
        logger.error(f"ETL verification failed: {e}")

    # 4. Start cache flush background task
    logger.info("Starting cache flush task...")
    try:
        from src.common.data_gatherer.db_stream_handlers import start_background_flush_task
        background_tasks["cache_flush"] = start_background_flush_task()
        logger.info("Cache flush task started")
    except Exception as e:
        logger.error(f"Cache flush task failed: {e}")

    # 5. Start data stream (controlled by config)
    if config.get("data_stream.enabled", default=False):
        logger.info("Starting real-time data stream...")
        try:
            from src.common.data_gatherer.alpaca_stream import AlpacaDataStreamer
            from src.common.data_gatherer.db_stream_handlers import save_trade_to_cache, save_bar_to_db
            from src.common.dao import AlpacaDAO

            dao = AlpacaDAO()
            watchlist = dao.get_watchlist()
            dao.close()

            if watchlist:
                symbol = watchlist[0]
                logger.info(f"Streaming data for: {symbol}")

                streamer = AlpacaDataStreamer(symbol=symbol)
                streamer.subscribe_trades(save_trade_to_cache)
                streamer.subscribe_bars(save_bar_to_db)

                background_tasks["data_stream"] = asyncio.create_task(
                    _run_stream_async(streamer)
                )
                logger.info("Data stream started")
            else:
                logger.warning("No watchlist symbols found, data stream not started")
        except Exception as e:
            logger.error(f"Data stream failed to start: {e}")
    else:
        logger.info("Data stream disabled in config")

    logger.info("=" * 70)
    logger.info("Application startup complete")
    logger.info("API Server: http://localhost:8001")
    logger.info("Interactive Docs: http://localhost:8001/docs")
    logger.info("=" * 70)

    # =========================================================================
    # APPLICATION RUNNING
    # =========================================================================
    yield

    # =========================================================================
    # SHUTDOWN
    # =========================================================================
    logger.info("=" * 70)
    logger.info("Shutting down LangGraph Portfolio Manager API...")
    logger.info("=" * 70)

    # Stop data stream
    if background_tasks["data_stream"]:
        logger.info("Stopping data stream...")
        background_tasks["data_stream"].cancel()
        try:
            await background_tasks["data_stream"]
        except asyncio.CancelledError:
            logger.info("   Data stream cancelled")

    # Flush remaining cached trades
    logger.info("Flushing remaining cached trades...")
    try:
        from src.common.data_gatherer.db_stream_handlers import flush_cache_to_db
        from src.common.data_gatherer.trade_cache import get_cache

        cache = get_cache()
        cache_size = len(cache._cache) if hasattr(cache, "_cache") else 0

        if cache_size > 0:
            logger.info(f"   Flushing {cache_size} trades before shutdown...")
            await flush_cache_to_db()
            logger.info("   Cache flushed")
        else:
            logger.info("   Cache is empty")
    except Exception as e:
        logger.error(f"   Failed to flush cache: {e}", exc_info=True)

    # Stop background flush task
    if background_tasks["cache_flush"]:
        logger.info("Stopping cache flush task...")
        try:
            from src.common.data_gatherer.db_stream_handlers import stop_background_flush_task
            await stop_background_flush_task()
            logger.info("   Cache flush task stopped")
        except Exception as e:
            logger.error(f"   Failed to stop flush task: {e}")

    # Close database connections
    logger.info("Closing database connections...")
    try:
        from src.common.data_gatherer.db_stream_handlers import get_dao
        dao = get_dao()
        if dao:
            dao.close()
            logger.info("   Database connections closed")
    except Exception as e:
        logger.error(f"   Failed to close database: {e}")

    _graph = None
    logger.info("=" * 70)
    logger.info("Shutdown complete")
    logger.info("=" * 70)


async def _run_stream_async(streamer) -> None:
    """Run data stream in async context.

    Args:
        streamer: AlpacaDataStreamer instance.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, streamer.run)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="LangGraph Portfolio Manager",
    description="Deterministic LangGraph agent replacing DeepAgent orchestration",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response schemas ────────────────────────────────────────────────


class QueryRequest(BaseModel):
    """Request body for /v1/query."""

    query: str = Field(..., description="Natural language query", min_length=1)
    thread_id: Optional[str] = Field(
        default=None,
        description="Conversation thread UUID. A new UUID is generated if omitted.",
    )
    backtest_mode: bool = Field(
        default=False,
        description="Bypass market hours and portfolio guards (for historical queries)",
    )
    apply_middleware: bool = Field(
        default=True,
        description="Whether to apply middleware stack (guards, tracing)",
    )
    model: Optional[str] = Field(
        default=None,
        description="Reserved for future model selection",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What is my portfolio status?",
                "thread_id": "user-session-123",
                "backtest_mode": False,
                "apply_middleware": True,
            }
        }


class QueryResponse(BaseModel):
    """Response body for /v1/query."""

    query: str
    response: Optional[str]
    intent: Optional[str]
    bt_workflow: Optional[str]
    symbol: Optional[str]
    thread_id: str
    timestamp: str
    execution_time_ms: Optional[int]
    tool_timings: Optional[list]
    status: str = Field(..., description="success | error")
    error: Optional[str]

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What is my portfolio status?",
                "response": "Your portfolio is valued at $100,000...",
                "intent": "portfolio",
                "thread_id": "user-session-123",
                "timestamp": "2026-03-25T16:00:00+00:00",
                "execution_time_ms": 1200,
                "status": "success",
                "error": None,
            }
        }


class HealthResponse(BaseModel):
    """Response body for basic health check."""

    status: str = Field(..., description="healthy | degraded | unhealthy")
    graph_ready: bool
    timestamp: str
    version: str


class DetailedHealthResponse(BaseModel):
    """Response body for detailed health check."""

    status: str = Field(..., description="healthy | degraded")
    timestamp: str
    checks: Dict[str, Any]


class AgentStateResponse(BaseModel):
    """Response body for graph checkpoint state."""

    status: str
    thread_id: str
    state: Optional[Dict]
    timestamp: str
    error: Optional[str]


class CleanupResponse(BaseModel):
    """Response body for thread cleanup."""

    deleted: Optional[int]
    dry_run: Optional[bool]
    would_delete: Optional[int]
    timestamp: str


class StatsResponse(BaseModel):
    """Response body for database statistics."""

    database_size_mb: float
    database_path: str
    tables: Dict[str, Any]
    timestamp: str


class IngestionStatusResponse(BaseModel):
    """Response body for ingestion pipeline status."""

    stream_running: bool
    cache_size: int
    indicator_count: int
    etl_enabled: bool
    timestamp: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _invoke_graph(request: QueryRequest) -> dict:
    """Run graph.invoke() with thread context management.

    Args:
        request: Validated QueryRequest.

    Returns:
        Final graph state dict.
    """
    thread_id = request.thread_id or str(uuid.uuid4())
    token = set_thread_id(thread_id)
    config_dict = {"configurable": {"thread_id": thread_id}}
    initial = _make_initial_state(request.query, thread_id, request.backtest_mode)

    try:
        start = time.time()
        result = _graph.invoke(initial, config=config_dict)
        result["execution_time_ms"] = int((time.time() - start) * 1000)
        result.setdefault("thread_id", thread_id)
        return result
    finally:
        reset_thread_id(token)


async def _stream_graph(request: QueryRequest) -> AsyncGenerator[str, None]:
    """Stream graph execution as Server-Sent Events.

    Args:
        request: Validated QueryRequest.

    Yields:
        SSE-formatted strings for each node step.
    """
    thread_id = request.thread_id or str(uuid.uuid4())
    token = set_thread_id(thread_id)
    config_dict = {"configurable": {"thread_id": thread_id}}
    initial = _make_initial_state(request.query, thread_id, request.backtest_mode)

    text_parts: list = []
    had_error = False

    try:
        yield f"data: {json.dumps({'type': 'status', 'message': 'Processing query...', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

        for step in _graph.stream(initial, config=config_dict):
            for node_name, node_output in step.items():
                # MemorySaver emits None for internal checkpointer steps
                if node_output is None:
                    node_output = {}
                ts = datetime.now(timezone.utc).isoformat()

                # 1. Raw node event (for custom clients / debugging)
                payload = {
                    "type": "node",
                    "node": node_name,
                    "data": {
                        k: v
                        for k, v in node_output.items()
                        if v is not None and k not in ("positions_summary", "portfolio_status")
                    },
                    "timestamp": ts,
                }
                yield f"data: {json.dumps(payload, default=str)}\n\n"

                # 2. UI-compatible events ────────────────────────────────────
                # Intermediate nodes → tool_call badge in the chat bubble
                _BADGE_NODES = {"portfolio_node", "quant_node", "backtester_node"}
                if node_name in _BADGE_NODES:
                    yield f"data: {json.dumps({'type': 'tool_call', 'content': node_name, 'timestamp': ts})}\n\n"

                # Synthesizer final_response → text event renders in bubble
                if node_name == "synthesizer":
                    final_resp = node_output.get("final_response")
                    if final_resp:
                        text_parts.append(str(final_resp))
                        yield f"data: {json.dumps({'type': 'text', 'content': final_resp, 'timestamp': ts}, default=str)}\n\n"

                await asyncio.sleep(0)

        if not had_error:
            _persist_conversation(
                thread_id=thread_id,
                user_query=request.query,
                assistant_text=" ".join(text_parts),
            )

        yield f"data: {json.dumps({'type': 'done', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

    except Exception as exc:
        had_error = True
        yield f"data: {json.dumps({'type': 'error', 'error': str(exc), 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
    finally:
        reset_thread_id(token)


def _persist_conversation(
    thread_id: str,
    user_query: str,
    assistant_text: str,
) -> None:
    """Append a user+assistant exchange to the on-disk conversation file.

    Args:
        thread_id: Client UUID for the conversation.
        user_query: User's original message.
        assistant_text: Concatenated synthesizer output.
    """
    conv_dir = Path("data/conversations")
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_path = conv_dir / f"{thread_id}.json"

    now = datetime.now(timezone.utc).isoformat()

    if conv_path.exists():
        try:
            with open(conv_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"thread_id": thread_id, "created_at": now, "messages": []}
    else:
        data = {"thread_id": thread_id, "created_at": now, "messages": []}

    data["messages"].append({"role": "user", "content": user_query, "timestamp": now})
    data["messages"].append({"role": "assistant", "content": assistant_text, "timestamp": now})
    data["updated_at"] = now

    with open(conv_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Register thread_id and log API-level interaction in DB
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        dao.save_thread_id(thread_id)
        dao.save_interaction(
            thread_id=thread_id,
            agent_name="api",
            user_query=user_query,
            tool_sequence=[{"node": "langgraph_graph"}],
            agent_response=assistant_text[:1000] if assistant_text else "",
            model_used="langgraph",
        )
        dao.close()
    except Exception as e:
        logger.warning(f"Failed to register thread_id in DB: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", tags=["Info"])
async def root() -> dict:
    """Root endpoint with API information."""
    return {
        "name": "LangGraph Portfolio Manager API",
        "version": "1.0.0",
        "description": "Deterministic LangGraph agent for portfolio management",
        "architecture": "StateGraph with classifier, guards, portfolio/quant/backtester nodes, synthesizer",
        "main_endpoint": "/v1/query",
        "docs": "/docs",
        "health": "/v1/health",
    }


@app.get("/v1/health", response_model=HealthResponse, tags=["System"])
async def health() -> HealthResponse:
    """Basic liveness check.

    Returns:
        HealthResponse with overall status and graph readiness.
    """
    graph_ready = _graph is not None
    return HealthResponse(
        status="healthy" if graph_ready else "degraded",
        graph_ready=graph_ready,
        timestamp=datetime.now(timezone.utc).isoformat(),
        version="1.0.0",
    )


@app.get("/v1/health/detailed", response_model=DetailedHealthResponse, tags=["System"])
async def detailed_health() -> DetailedHealthResponse:
    """Comprehensive system health check.

    Checks all critical components:
    - LangGraph compilation
    - DuckDB database
    - Alpaca Trading API
    - Anthropic API

    Returns:
        DetailedHealthResponse with per-component status.
    """
    checks: Dict[str, Any] = {}

    # LangGraph
    checks["langgraph"] = {
        "status": "healthy" if _graph is not None else "unhealthy",
        "graph_ready": _graph is not None,
    }

    # DuckDB
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        dao.fetch_one("SELECT 1")
        dao.close()
        checks["database"] = {"status": "healthy", "type": "DuckDB"}
    except Exception as e:
        logger.error(f"Database check failed: {e}")
        checks["database"] = {"status": "unhealthy", "error": str(e)}

    # Alpaca API
    try:
        from alpaca.trading import TradingClient
        from src.common.utils import secrets
        client = TradingClient(
            secrets.get("alpaca.api_key"),
            secrets.get("alpaca.secret_key"),
        )
        account = client.get_account()
        checks["alpaca_api"] = {"status": "healthy", "account_status": account.status}
    except Exception as e:
        logger.error(f"Alpaca API check failed: {e}")
        checks["alpaca_api"] = {"status": "unhealthy", "error": str(e)}

    # Anthropic API
    try:
        import anthropic
        from src.common.utils import secrets
        client = anthropic.Anthropic(api_key=secrets.get("anthropic.api_key"))
        client.models.list()
        checks["anthropic_api"] = {"status": "healthy"}
    except Exception as e:
        logger.error(f"Anthropic API check failed: {e}")
        checks["anthropic_api"] = {"status": "unhealthy", "error": str(e)}

    all_healthy = all(c.get("status") == "healthy" for c in checks.values())

    return DetailedHealthResponse(
        status="healthy" if all_healthy else "degraded",
        timestamp=datetime.now(timezone.utc).isoformat(),
        checks=checks,
    )


@app.post("/v1/query", response_model=QueryResponse, tags=["Portfolio Manager"])
async def query(request: QueryRequest) -> QueryResponse:
    """Invoke the LangGraph agent and return the final response.

    Args:
        request: QueryRequest with query, thread_id, backtest_mode.

    Returns:
        QueryResponse with response, intent, and metadata.

    Raises:
        HTTPException 503: If graph is not initialized.
    """
    if _graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph not initialized",
        )

    logger.info(f"[api] query='{request.query[:80]}' backtest={request.backtest_mode}")

    thread_id = request.thread_id or str(uuid.uuid4())

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _invoke_graph, request
        )

        return QueryResponse(
            query=request.query,
            response=result.get("final_response"),
            intent=result.get("intent"),
            bt_workflow=result.get("bt_workflow"),
            symbol=result.get("symbol"),
            thread_id=result.get("thread_id", thread_id),
            timestamp=result.get("timestamp", datetime.now(timezone.utc).isoformat()),
            execution_time_ms=result.get("execution_time_ms"),
            tool_timings=result.get("tool_timings"),
            status="success",
            error=result.get("routing_error") or result.get("error"),
        )

    except Exception as exc:
        logger.error(f"[api] graph error: {exc}", exc_info=True)
        return QueryResponse(
            query=request.query,
            response=None,
            intent=None,
            bt_workflow=None,
            symbol=None,
            thread_id=thread_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            execution_time_ms=None,
            tool_timings=None,
            status="error",
            error=str(exc),
        )


@app.post("/v1/query/stream", tags=["Portfolio Manager"])
async def query_stream(request: QueryRequest) -> StreamingResponse:
    """Stream graph execution as Server-Sent Events.

    Returns real-time events as the graph processes the query:
    - status: Processing started
    - node: Per-node output as graph steps through
    - error: If processing failed
    - done: Processing complete

    Args:
        request: QueryRequest with query, thread_id, backtest_mode.

    Returns:
        StreamingResponse with SSE events per node step.

    Raises:
        HTTPException 503: If graph is not initialized.
    """
    if _graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph not initialized",
        )

    logger.info(f"[api/stream] query='{request.query[:80]}'")

    return StreamingResponse(
        _stream_graph(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/v1/conversations/{thread_id}", tags=["Conversations"])
async def get_conversation(thread_id: str) -> dict:
    """Load conversation history for a thread from disk.

    Args:
        thread_id: Client-generated UUID for the conversation.

    Returns:
        Dict with thread_id and list of messages.
    """
    conv_path = Path("data/conversations") / f"{thread_id}.json"
    if not conv_path.exists():
        return {"thread_id": thread_id, "messages": []}

    try:
        with open(conv_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load conversation {thread_id}: {e}")
        return {"thread_id": thread_id, "messages": []}


@app.get("/v1/portfolio/status", tags=["Portfolio"])
async def get_portfolio_status() -> dict:
    """Get current portfolio status from database.

    Returns latest snapshot with equity, cash, positions, and P&L.

    Returns:
        Latest portfolio snapshot or message if none available.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        snapshot = dao.get_latest_snapshot()
        dao.close()

        return {
            "status": "success",
            "snapshot": snapshot,
            "message": None if snapshot else "No portfolio snapshot available",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to fetch portfolio status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/portfolio/health", tags=["Portfolio"])
async def get_portfolio_health() -> dict:
    """Get portfolio health status with risk compliance checks.

    Returns:
        Health status with violations and warnings.
    """
    try:
        from src.agentic.agents.portfolio_tools import check_portfolio_health

        result = check_portfolio_health.invoke({})
        health_data = json.loads(result)

        return {
            "status": "success",
            "health": health_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to check portfolio health: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/portfolio/history", tags=["Portfolio"])
async def get_portfolio_history(
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
) -> dict:
    """Get historical portfolio snapshots.

    Args:
        start: Start date for history (optional).
        end: End date for history (optional).

    Returns:
        List of portfolio snapshots.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        history = dao.get_snapshot_history(start_date=start, end_date=end)
        dao.close()

        return {
            "status": "success",
            "snapshots": history,
            "count": len(history),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to fetch portfolio history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/agent/state/{thread_id}", response_model=AgentStateResponse, tags=["Debug"])
async def get_agent_state(thread_id: str) -> AgentStateResponse:
    """Get LangGraph checkpoint state for a given thread.

    Useful for debugging — shows which node last ran, intent, routing errors,
    and the final synthesized response for the thread.

    Args:
        thread_id: Thread ID to inspect.

    Returns:
        AgentStateResponse with checkpoint state.
    """
    try:
        if _graph is None:
            raise RuntimeError("Graph not initialized")

        config_dict = {"configurable": {"thread_id": thread_id}}
        checkpoint = _graph.get_state(config_dict)
        state_dict = dict(checkpoint.values) if checkpoint and checkpoint.values else {}

        return AgentStateResponse(
            status="success",
            thread_id=thread_id,
            state=state_dict,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=None,
        )

    except Exception as e:
        logger.error(f"Failed to retrieve agent state: {e}")
        return AgentStateResponse(
            status="error",
            thread_id=thread_id,
            state=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=str(e),
        )


@app.post("/v1/admin/cleanup", response_model=CleanupResponse, tags=["Admin"])
async def trigger_cleanup(
    dry_run: bool = Query(False, description="Dry run mode (don't actually delete)")
) -> CleanupResponse:
    """Trigger thread cleanup manually.

    Deletes expired agent interactions from database based on expires_at timestamp.

    Args:
        dry_run: If True, only report what would be deleted.

    Returns:
        CleanupResponse with deletion stats.
    """
    try:
        from src.common.utils.maintenance import cleanup_expired_threads
        result = cleanup_expired_threads(dry_run=dry_run)
        return CleanupResponse(**result)

    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Maintenance utilities not yet implemented",
        )
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/admin/stats", response_model=StatsResponse, tags=["Admin"])
async def get_database_stats() -> StatsResponse:
    """Get database statistics and table row counts.

    Returns:
        StatsResponse with database size and table statistics.
    """
    try:
        from src.common.utils.maintenance import get_database_stats
        result = get_database_stats()
        return StatsResponse(**result)

    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Maintenance utilities not yet implemented",
        )
    except Exception as e:
        logger.error(f"Stats retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/ingestion/status", response_model=IngestionStatusResponse, tags=["Ingestion"])
async def ingestion_status() -> IngestionStatusResponse:
    """Get real-time data ingestion pipeline status.

    Reports:
    - Whether the WebSocket data stream is running
    - Number of trades cached in memory
    - Number of pre-computed indicator rows in DB
    - Whether ETL auto-computation is enabled

    Returns:
        IngestionStatusResponse with pipeline state.
    """
    stream_running = background_tasks.get("data_stream") is not None
    cache_size = 0
    indicator_count = 0

    try:
        from src.common.data_gatherer.trade_cache import get_cache
        cache = get_cache()
        cache_size = len(cache._cache) if hasattr(cache, "_cache") else 0
    except Exception as e:
        logger.debug(f"Cache size check failed: {e}")

    try:
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        df = dao.fetch_df("SELECT COUNT(*) as cnt FROM computed_indicators")
        indicator_count = int(df["cnt"].iloc[0]) if not df.empty else 0
        dao.close()
    except Exception as e:
        logger.debug(f"Indicator count check failed: {e}")

    etl_enabled = config.get("etl.enabled", default=True)

    return IngestionStatusResponse(
        stream_running=stream_running,
        cache_size=cache_size,
        indicator_count=indicator_count,
        etl_enabled=etl_enabled,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/v1/ingestion/trigger-etl", tags=["Ingestion"])
async def trigger_etl() -> dict:
    """Manually trigger the ETL indicator computation pipeline.

    Fetches watchlist symbols and runs indicator computation for each,
    storing results in computed_indicators table.

    Returns:
        Dict with status, symbols processed, and timestamp.
    """
    try:
        from src.common.etl.pipeline import ETLPipeline
        from src.common.dao import AlpacaDAO

        dao = AlpacaDAO()
        symbols = dao.get_watchlist()
        dao.close()

        if not symbols:
            return {
                "status": "skipped",
                "reason": "No symbols in watchlist",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        pipeline = ETLPipeline()
        await asyncio.get_event_loop().run_in_executor(None, pipeline.run)

        return {
            "status": "success",
            "symbols": symbols,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"ETL trigger failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/ingestion/flush-cache", tags=["Ingestion"])
async def flush_trade_cache() -> dict:
    """Flush the in-memory trade cache to the database.

    Forces immediate persistence of any buffered trade data that hasn't
    yet been written by the background flush task.

    Returns:
        Dict with status, flushed count, and timestamp.
    """
    try:
        from src.common.data_gatherer.db_stream_handlers import flush_cache_to_db
        from src.common.data_gatherer.trade_cache import get_cache

        cache = get_cache()
        pre_flush_size = len(cache._cache) if hasattr(cache, "_cache") else 0

        await flush_cache_to_db()

        return {
            "status": "success",
            "flushed_count": pre_flush_size,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Cache flush failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/tools", tags=["Info"])
async def list_tools() -> dict:
    """List available nodes and their tools within the LangGraph.

    Returns:
        Dict with tool information per graph node.
    """
    return {
        "graph_nodes": [
            "classify_intent",
            "market_hours_guard",
            "portfolio_guard",
            "portfolio_node",
            "quant_node",
            "backtester_node",
            "synthesizer",
        ],
        "portfolio_node_tools": [
            {
                "name": "get_portfolio_status",
                "description": "Fetch current account equity, cash, buying power, positions",
                "caching": "5 minutes",
            },
            {
                "name": "get_positions_summary",
                "description": "Get detailed position information with P&L breakdown",
                "caching": "5 minutes",
            },
            {
                "name": "check_portfolio_health",
                "description": "Validate portfolio against risk parameters",
                "caching": "None (always fresh)",
            },
        ],
        "quant_node_tools": [
            {
                "name": "get_market_bars",
                "description": "Fetch OHLCV market data for analysis",
            },
            {
                "name": "get_company_fundamentals",
                "description": "Fetch company fundamental data from Alpha Vantage",
            },
            {
                "name": "fetch_historical_data",
                "description": "Fetch historical market data for a symbol",
            },
            {
                "name": "check_data_availability",
                "description": "Check if historical data exists for symbol and date range",
            },
        ],
        "backtester_node_tools": [
            {
                "name": "run_backtest",
                "description": "Execute backtesting strategy over historical data",
            },
            {
                "name": "get_backtest_results",
                "description": "Retrieve stored backtest results from database",
            },
        ],
    }


if __name__ == "__main__":
    """Integration test: start server and verify health endpoint."""
    import uvicorn
    import threading
    import time as _time

    print("=" * 60)
    print("LangGraph API Integration Test")
    print("=" * 60)

    # Start server in background thread
    print("\n[1/3] Starting uvicorn on port 8001...")
    server_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    server_thread.start()
    _time.sleep(2)

    # Test health endpoint
    print("\n[2/3] GET /v1/health")
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8001/v1/health") as resp:
            health_data = json.loads(resp.read())
            assert health_data["status"] in ("healthy", "degraded")
            assert "graph_ready" in health_data
            print(f"[OK] health: {health_data}")
    except Exception as exc:
        print(f"[FAIL] health check: {exc}")

    # Test query endpoint
    print("\n[3/3] POST /v1/query")
    try:
        import urllib.request
        req_data = json.dumps({
            "query": "What is my portfolio status?",
            "backtest_mode": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:8001/v1/query",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            assert result.get("status") in ("success", "error")
            print(f"[OK] status={result['status']} intent={result.get('intent')}")
            if result.get("response"):
                print(f"     response preview: {result['response'][:100]}...")
    except Exception as exc:
        print(f"[FAIL] query: {exc}")

    print("\n" + "=" * 60)
    print("API integration test complete!")
