"""FastAPI server for Portfolio Manager agent.

Provides REST API for:
- Portfolio status and health checks
- Natural language queries to Portfolio Manager
- Automatic delegation to Quant Analyst for technical analysis
- Agent state inspection and observability
- Database maintenance utilities

Architecture: All queries go through Portfolio Manager, which internally
delegates to Quant Analyst when needed. This ensures risk checks and
proper coordination.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

from src.common.dao.portfolio_dao import PortfolioDAO
from src.common.core.thread_context import set_thread_id, reset_thread_id
from src.common.utils import get_logger, config
from src.agentic.agents.portfolio.manager import PortfolioManager

logger = get_logger(__name__)

# Global background tasks
background_tasks = {
    'data_stream': None,
    'cache_flush': None
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown."""
    # ═══════════════════════════════════════════════════════════════
    # STARTUP
    # ═══════════════════════════════════════════════════════════════
    logger.info("="*70)
    logger.info("🚀 Starting Agentic Portfolio Manager...")
    logger.info("="*70)

    # 1. Sync watchlist from Alpaca to database
    logger.info("📋 Syncing watchlist from Alpaca...")
    try:
        from src.common.skills.alpaca_portfolio_skills import get_all_watchlist_symbols
        from src.common.dao import AlpacaDAO

        # Fetch symbols from Alpaca watchlists
        alpaca_symbols = get_all_watchlist_symbols()

        # Fallback to config if Alpaca has no watchlists
        if not alpaca_symbols:
            logger.warning("⚠️ No watchlists in Alpaca, using config fallback")
            alpaca_symbols = config.get("watchlist", default=["AAPL"])
            logger.info(f"   Fallback watchlist: {alpaca_symbols}")

        if alpaca_symbols:
            # Sync to database
            dao = AlpacaDAO()

            # Get current DB watchlist
            db_symbols = set(dao.get_watchlist())
            alpaca_symbols_set = set(alpaca_symbols)

            # Add new symbols
            symbols_to_add = alpaca_symbols_set - db_symbols
            for symbol in symbols_to_add:
                dao.add_to_watchlist(symbol)
                logger.info(f"   Added {symbol} to watchlist")

            # Optionally remove symbols not in Alpaca (commented out for safety)
            # symbols_to_remove = db_symbols - alpaca_symbols_set
            # for symbol in symbols_to_remove:
            #     dao.remove_from_watchlist(symbol)
            #     logger.info(f"   Removed {symbol} from watchlist")

            dao.close()
            logger.info(f"✅ Watchlist synced: {len(alpaca_symbols)} symbols ({len(symbols_to_add)} added)")
        else:
            logger.warning("⚠️ No watchlist configured")

    except Exception as e:
        logger.error(f"❌ Watchlist sync failed: {e}")
        logger.warning("   Will use existing database watchlist")

    # 2. Verify ETL configuration
    logger.info("🔧 Verifying ETL configuration...")
    try:
        etl_enabled = config.get("etl.enabled", default=True)
        lookback_days = config.get("etl.lookback_days", default=60)

        if etl_enabled:
            logger.info(f"✓ ETL auto-computation ENABLED (lookback: {lookback_days} days)")
        else:
            logger.warning("⚠️  ETL auto-computation DISABLED - indicators will not be computed during ingestion")

        # Verify computed_indicators table has data
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        try:
            indicator_count = dao.fetch_df("SELECT COUNT(*) as cnt FROM computed_indicators")
            count = indicator_count['cnt'].iloc[0] if not indicator_count.empty else 0
            logger.info(f"📊 Current computed indicators in DB: {count:,} rows")
        except Exception:
            logger.warning("⚠️  computed_indicators table may not exist yet")
        finally:
            dao.close()
    except Exception as e:
        logger.error(f"❌ ETL verification failed: {e}")

    # 3. Start cache flush background task
    logger.info("📦 Starting cache flush task...")
    from src.common.data_gatherer.db_stream_handlers import start_background_flush_task
    try:
        background_tasks['cache_flush'] = start_background_flush_task()
        logger.info("✅ Cache flush task started")
    except Exception as e:
        logger.error(f"❌ Cache flush task failed: {e}")

    # 4. Start data stream (optional - controlled by config)
    if config.get("data_stream.enabled", default=False):
        logger.info("📡 Starting real-time data stream...")
        try:
            from src.common.data_gatherer.alpaca_stream import AlpacaDataStreamer
            from src.common.data_gatherer.db_stream_handlers import save_trade_to_cache, save_bar_to_db
            from src.common.dao import AlpacaDAO

            # Get watchlist symbols
            dao = AlpacaDAO()
            watchlist = dao.get_watchlist()
            dao.close()

            if watchlist:
                symbol = watchlist[0]  # Start with first symbol
                logger.info(f"📊 Streaming data for: {symbol}")

                streamer = AlpacaDataStreamer(symbol=symbol)
                streamer.subscribe_trades(save_trade_to_cache)
                streamer.subscribe_bars(save_bar_to_db)

                # Run stream in background
                background_tasks['data_stream'] = asyncio.create_task(
                    run_stream_async(streamer)
                )
                logger.info("✅ Data stream started")
            else:
                logger.warning("⚠️ No watchlist symbols found, data stream not started")
        except Exception as e:
            logger.error(f"❌ Data stream failed to start: {e}")
    else:
        logger.info("⏸️ Data stream disabled in config")

    # 4. ETL auto-runs with bar streaming (no separate scheduler needed)
    logger.info("⚙️ ETL configured to auto-run with bar ingestion")
    logger.info(f"   - Indicators computed automatically when bars are saved")
    logger.info(f"   - Lookback window: {config.get('etl.lookback_days', default=60)} days")
    logger.info(f"   - Timeframes: {config.get('etl.timeframes', default=['1Min', '1Hour', '1Day'])}")

    logger.info("="*70)
    logger.info("✅ Application startup complete")
    logger.info("🌐 API Server: http://localhost:8000")
    logger.info("📚 Interactive Docs: http://localhost:8000/docs")
    logger.info("="*70)

    # ═══════════════════════════════════════════════════════════════
    # APPLICATION RUNNING
    # ═══════════════════════════════════════════════════════════════
    yield  # FastAPI runs here

    # ═══════════════════════════════════════════════════════════════
    # SHUTDOWN
    # ═══════════════════════════════════════════════════════════════
    logger.info("="*70)
    logger.info("🛑 Shutting down Agentic Portfolio Manager...")
    logger.info("="*70)

    # Step 1: Stop data stream first (stop new data from coming in)
    if background_tasks['data_stream']:
        logger.info("📡 Stopping data stream...")
        background_tasks['data_stream'].cancel()
        try:
            await background_tasks['data_stream']
        except asyncio.CancelledError:
            logger.info("   Data stream cancelled")

    # Step 2: Flush remaining cached trades to database
    logger.info("📦 Flushing remaining cached trades...")
    try:
        from src.common.data_gatherer.db_stream_handlers import flush_cache_to_db, get_dao
        from src.common.data_gatherer.trade_cache import get_cache

        cache = get_cache()
        cache_size = len(cache._cache) if hasattr(cache, '_cache') else 0

        if cache_size > 0:
            logger.info(f"   Flushing {cache_size} trades before shutdown...")
            await flush_cache_to_db()
            logger.info("   ✅ Cache flushed")
        else:
            logger.info("   Cache is empty")
    except Exception as e:
        logger.error(f"   Failed to flush cache: {e}", exc_info=True)

    # Step 3: Stop background flush task
    if background_tasks['cache_flush']:
        logger.info("📦 Stopping cache flush task...")
        try:
            from src.common.data_gatherer.db_stream_handlers import stop_background_flush_task
            await stop_background_flush_task()
            logger.info("   ✅ Cache flush task stopped")
        except Exception as e:
            logger.error(f"   Failed to stop flush task: {e}")

    # Step 4: Close database connections
    logger.info("🗄️  Closing database connections...")
    try:
        from src.common.data_gatherer.db_stream_handlers import get_dao
        dao = get_dao()
        if dao:
            dao.close()
            logger.info("   ✅ Database connections closed")
    except Exception as e:
        logger.error(f"   Failed to close database: {e}")

    logger.info("="*70)
    logger.info("✅ Shutdown complete")
    logger.info("="*70)


async def run_stream_async(streamer):
    """Run data stream in async context."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, streamer.run)


# Create FastAPI app with lifespan
app = FastAPI(
    title="Agentic Portfolio Manager API",
    description="Portfolio Manager Agent with Risk Management and Technical Analysis Delegation",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Portfolio Manager (singleton)
portfolio_manager = None


def get_portfolio_manager():
    """Get or create Portfolio Manager instance."""
    global portfolio_manager
    if portfolio_manager is None:
        portfolio_manager = PortfolioManager(
            model="gpt-5-mini",
            backtest_mode=True  # Set to False in production for middleware enforcement
        )
        logger.info("Portfolio Manager initialized")
    return portfolio_manager


# Request/Response models
class QueryRequest(BaseModel):
    """Request model for Portfolio Manager queries."""
    query: str = Field(..., description="Natural language query for Portfolio Manager", min_length=1)
    thread_id: str = Field("default", description="Thread ID for conversation context")
    apply_middleware: bool = Field(True, description="Whether to apply middleware stack (guards, tracing)")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What's my portfolio status? Should I buy AAPL?",
                "thread_id": "user-session-123",
                "apply_middleware": True
            }
        }


class QueryResponse(BaseModel):
    """Response model for Portfolio Manager queries."""
    query: str = Field(..., description="Original query")
    response: str = Field(..., description="Agent response")
    timestamp: str = Field(..., description="ISO timestamp")
    thread_id: str = Field(..., description="Thread ID used")
    model: str = Field(..., description="LLM model used")
    execution_time_ms: Optional[int] = Field(None, description="Execution time in milliseconds")
    tool_timings: Optional[List[Dict]] = Field(None, description="Tool performance timings")
    status: str = Field(..., description="Status: success | error")
    error: Optional[str] = Field(None, description="Error message if status is error")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What's my portfolio status?",
                "response": "Your portfolio is valued at $100,000...",
                "timestamp": "2026-02-25T16:00:00",
                "thread_id": "user-session-123",
                "model": "gpt-5-mini",
                "execution_time_ms": 2500,
                "tool_timings": [{"tool": "get_portfolio_status", "duration_ms": 150, "status": "success"}],
                "status": "success",
                "error": None
            }
        }


class HealthResponse(BaseModel):
    """Response model for basic health check."""
    status: str = Field(..., description="healthy | degraded | unhealthy")
    timestamp: str = Field(..., description="ISO timestamp of health check")
    version: str = Field(..., description="API version")


class DetailedHealthResponse(BaseModel):
    """Response model for detailed health check (Improvement #5)."""
    status: str = Field(..., description="healthy | degraded")
    timestamp: str = Field(..., description="ISO timestamp")
    checks: Dict[str, Any] = Field(..., description="Component health details")


class AgentStateResponse(BaseModel):
    """Response model for agent state inspection (Improvement #12)."""
    status: str = Field(..., description="success | error")
    thread_id: str = Field(..., description="Thread ID")
    state: Optional[Dict] = Field(None, description="Agent state with messages and tool calls")
    timestamp: str = Field(..., description="ISO timestamp")
    error: Optional[str] = Field(None, description="Error message if failed")


class CleanupResponse(BaseModel):
    """Response model for thread cleanup (Improvement #10)."""
    deleted: Optional[int] = Field(None, description="Number of interactions deleted")
    dry_run: Optional[bool] = Field(None, description="Whether this was a dry run")
    would_delete: Optional[int] = Field(None, description="Number that would be deleted (dry run)")
    timestamp: str = Field(..., description="ISO timestamp")


class StatsResponse(BaseModel):
    """Response model for database statistics."""
    database_size_mb: float = Field(..., description="Database size in MB")
    database_path: str = Field(..., description="Path to database file")
    tables: Dict[str, Any] = Field(..., description="Row counts per table")
    timestamp: str = Field(..., description="ISO timestamp")


class IngestionStatusResponse(BaseModel):
    """Response model for ingestion pipeline status."""
    data_stream: Dict[str, Any] = Field(..., description="Data stream status")
    cache: Dict[str, Any] = Field(..., description="Trade cache status")
    etl: Dict[str, Any] = Field(..., description="ETL scheduler status")
    timestamp: str = Field(..., description="ISO timestamp")


class ETLTriggerResponse(BaseModel):
    """Response model for manual ETL trigger."""
    status: str = Field(..., description="success | error")
    message: str = Field(..., description="Status message")
    total_rows: Optional[int] = Field(None, description="Total indicators computed")
    symbols: Optional[List[str]] = Field(None, description="Symbols processed")
    timestamp: str = Field(..., description="ISO timestamp")
    error: Optional[str] = Field(None, description="Error message if failed")


class CacheFlushResponse(BaseModel):
    """Response model for manual cache flush."""
    status: str = Field(..., description="success | error")
    message: str = Field(..., description="Status message")
    trades_flushed: Optional[int] = Field(None, description="Number of trades flushed")
    timestamp: str = Field(..., description="ISO timestamp")
    error: Optional[str] = Field(None, description="Error message if failed")


# Routes
@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Agentic Portfolio Manager API",
        "version": "2.0.0",
        "description": "Portfolio Manager with Risk Management and Technical Analysis",
        "architecture": "Single entry point via Portfolio Manager, delegates to Quant Analyst internally",
        "main_endpoint": "/query",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Basic health check endpoint.

    Returns:
        HealthResponse with overall status
    """
    try:
        # Quick check - try to get Portfolio Manager
        manager = get_portfolio_manager()
        status = "healthy"
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        status = "unhealthy"

    return HealthResponse(
        status=status,
        timestamp=datetime.now().isoformat(),
        version="2.0.0"
    )


@app.get("/health/detailed", response_model=DetailedHealthResponse, tags=["System"])
async def detailed_health():
    """Comprehensive system health check (Improvement #5).

    Checks all critical components:
    - DuckDB database
    - Alpaca Trading API
    - OpenAI API
    - Portfolio Manager agent

    Returns:
        DetailedHealthResponse with per-component status
    """
    checks = {}

    # Check DuckDB
    try:
        from src.common.dao import PortfolioDAO
        dao = PortfolioDAO()
        dao.fetch_one("SELECT 1")
        dao.close()
        checks["database"] = {"status": "healthy", "type": "DuckDB"}
    except Exception as e:
        logger.error(f"Database check failed: {e}")
        checks["database"] = {"status": "unhealthy", "error": str(e)}

    # Check Alpaca API
    try:
        from alpaca.trading import TradingClient
        from src.common.utils import secrets
        client = TradingClient(
            secrets.get("alpaca.api_key"),
            secrets.get("alpaca.secret_key")
        )
        account = client.get_account()
        checks["alpaca_api"] = {
            "status": "healthy",
            "account_status": account.status
        }
    except Exception as e:
        logger.error(f"Alpaca API check failed: {e}")
        checks["alpaca_api"] = {"status": "unhealthy", "error": str(e)}

    # Check OpenAI API
    try:
        from openai import OpenAI
        from src.common.utils import secrets
        client = OpenAI(api_key=secrets.get("openai.api_key"))
        # Simple test call
        client.models.list()
        checks["openai_api"] = {"status": "healthy"}
    except Exception as e:
        logger.error(f"OpenAI API check failed: {e}")
        checks["openai_api"] = {"status": "unhealthy", "error": str(e)}

    # Check Portfolio Manager
    try:
        manager = get_portfolio_manager()
        checks["portfolio_manager"] = {
            "status": "healthy",
            "model": manager.model,
            "backtest_mode": manager.backtest_mode
        }
    except Exception as e:
        logger.error(f"Portfolio Manager check failed: {e}")
        checks["portfolio_manager"] = {"status": "unhealthy", "error": str(e)}

    # Overall status
    all_healthy = all(c.get("status") == "healthy" for c in checks.values())

    return DetailedHealthResponse(
        status="healthy" if all_healthy else "degraded",
        timestamp=datetime.now().isoformat(),
        checks=checks
    )


@app.post("/query", response_model=QueryResponse, tags=["Portfolio Manager"])
async def query_portfolio_manager(request: QueryRequest):
    """Main entry point for all Portfolio Manager queries.

    This is the single endpoint for interacting with the system. Portfolio Manager
    handles all queries and internally delegates to Quant Analyst when technical
    analysis is needed.

    Examples:
    - "What's my portfolio status?"
    - "Is my portfolio healthy?"
    - "Should I buy AAPL?" (triggers technical analysis delegation)
    - "Show my positions with P&L"
    - "Analyze TSLA using mean reversion strategy" (delegated internally)

    Args:
        request: QueryRequest with natural language query and thread_id

    Returns:
        QueryResponse with Portfolio Manager's response

    Raises:
        HTTPException: If middleware blocks execution (market closed, loss limits)
    """
    logger.info(f"Received query: {request.query} (thread: {request.thread_id})")

    ctx_token = set_thread_id(request.thread_id)
    try:
        # Get Portfolio Manager
        manager = get_portfolio_manager()

        # Execute query with thread context
        result = manager.invoke(
            query=request.query,
            thread_id=request.thread_id,
            apply_middleware=request.apply_middleware
        )

        # Check if there was an error in result
        if "error" in result:
            return QueryResponse(
                query=result["query"],
                response="",
                timestamp=result["timestamp"],
                thread_id=result["thread_id"],
                model=result["model"],
                execution_time_ms=None,
                tool_timings=None,
                status="error",
                error=result["error"]
            )

        return QueryResponse(
            query=result["query"],
            response=result["response"],
            timestamp=result["timestamp"],
            thread_id=result["thread_id"],
            model=result["model"],
            execution_time_ms=result.get("execution_time_ms"),
            tool_timings=result.get("tool_timings"),
            status="success",
            error=None
        )

    except RuntimeError as e:
        # Middleware blocked execution (market hours, loss limits, etc.)
        logger.warning(f"Query blocked by middleware: {e}")
        raise HTTPException(status_code=403, detail=str(e))

    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        return QueryResponse(
            query=request.query,
            response="",
            timestamp=datetime.now().isoformat(),
            thread_id=request.thread_id,
            model="unknown",
            execution_time_ms=None,
            tool_timings=None,
            status="error",
            error=str(e)
        )

    finally:
        reset_thread_id(ctx_token)


@app.post("/query/stream", tags=["Portfolio Manager"])
async def query_portfolio_manager_stream(request: QueryRequest):
    """Stream Portfolio Manager execution with reasoning and tool calls via SSE.

    Returns real-time events as the agent processes the query:
    - status: Processing started
    - reasoning: Agent's internal thoughts
    - text: Agent's text output
    - tool: Tool calls being executed
    - error: If processing failed
    - done: Processing complete

    Args:
        request: Query request with natural language query and thread_id

    Returns:
        Server-Sent Events stream with real-time updates
    """
    logger.info(f"Streaming query received: {request.query}")

    async def event_generator():
        # Accumulators for conversation persistence
        text_parts: list = []
        reasoning_parts: list = []
        tool_names: list = []
        had_error = False

        # Propagate client UUID into ContextVar so delegation tools
        # can derive consistent bt-<uuid> / qa-<uuid> thread IDs
        ctx_token = set_thread_id(request.thread_id)
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing query...', 'timestamp': datetime.now().isoformat()})}\n\n"

            manager = get_portfolio_manager()

            for chunk in manager.stream(
                query=request.query,
                thread_id=request.thread_id
            ):
                chunk_type = chunk.get("type")
                content = chunk.get("content")

                # Accumulate for persistence
                if chunk_type == "text" and content:
                    text_parts.append(str(content))
                elif chunk_type == "reasoning" and content:
                    reasoning_parts.append(str(content))
                elif chunk_type == "tool_call" and content:
                    # Extract tool name if possible
                    if isinstance(content, dict):
                        for msg in content.get("messages", []):
                            if hasattr(msg, "name"):
                                tool_names.append(msg.name)
                    tool_names.append("tool")

                if chunk_type == "error":
                    had_error = True
                    event_data = {
                        "type": "error",
                        "error": content,
                        "timestamp": chunk.get("timestamp")
                    }
                else:
                    event_data = {
                        "type": chunk_type,
                        "content": content,
                        "step": chunk.get("step"),
                        "timestamp": chunk.get("timestamp")
                    }

                yield f"data: {json.dumps(event_data, default=str)}\n\n"

            # Persist conversation to disk and register thread_id in DB
            if not had_error:
                _persist_conversation(
                    thread_id=request.thread_id,
                    user_query=request.query,
                    assistant_text=" ".join(text_parts),
                    reasoning=" ".join(reasoning_parts),
                    tool_calls=list(dict.fromkeys(tool_names))  # deduplicate, preserve order
                )

            yield f"data: {json.dumps({'type': 'done', 'timestamp': datetime.now().isoformat()})}\n\n"

        except RuntimeError as e:
            logger.warning(f"Streaming query blocked by middleware: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e), 'blocked': True, 'timestamp': datetime.now().isoformat()})}\n\n"

        except Exception as e:
            logger.error(f"Streaming query failed: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e), 'timestamp': datetime.now().isoformat()})}\n\n"

        finally:
            reset_thread_id(ctx_token)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


def _persist_conversation(
    thread_id: str,
    user_query: str,
    assistant_text: str,
    reasoning: str,
    tool_calls: list
) -> None:
    """Append a user+assistant exchange to the on-disk conversation file and register thread.

    Args:
        thread_id: Client UUID for the conversation
        user_query: User's message
        assistant_text: Concatenated text output from the assistant
        reasoning: Concatenated reasoning blocks
        tool_calls: List of tool names called
    """
    conv_dir = Path("data/conversations")
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_path = conv_dir / f"{thread_id}.json"

    now = datetime.now().isoformat()

    # Load existing or create new
    if conv_path.exists():
        try:
            with open(conv_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"thread_id": thread_id, "created_at": now, "messages": []}
    else:
        data = {"thread_id": thread_id, "created_at": now, "messages": []}

    data["messages"].append({"role": "user", "content": user_query, "timestamp": now})
    data["messages"].append({
        "role": "assistant",
        "content": assistant_text,
        "reasoning": reasoning,
        "tool_calls": tool_calls,
        "timestamp": now
    })
    data["updated_at"] = now

    with open(conv_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Register thread_id in DB
    try:
        dao = PortfolioDAO()
        dao.save_thread_id(thread_id)
        dao.close()
    except Exception as e:
        logger.warning(f"Failed to register thread_id in DB: {e}")


@app.get("/conversations/{thread_id}", tags=["Conversations"])
async def get_conversation(thread_id: str):
    """Load conversation history for a thread from disk.

    Args:
        thread_id: Client-generated UUID for the conversation

    Returns:
        List of messages, empty list if no conversation found
    """
    conv_path = Path("data/conversations") / f"{thread_id}.json"
    if not conv_path.exists():
        return {"thread_id": thread_id, "messages": []}

    try:
        with open(conv_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.error(f"Failed to load conversation {thread_id}: {e}")
        return {"thread_id": thread_id, "messages": []}


@app.get("/portfolio/status", tags=["Portfolio"])
async def get_portfolio_status():
    """Get current portfolio status from database.

    Returns latest snapshot with equity, cash, positions, and P&L.

    Returns:
        Latest portfolio snapshot or error
    """
    try:
        from src.common.dao import PortfolioDAO
        dao = PortfolioDAO()
        snapshot = dao.get_latest_snapshot()
        dao.close()

        if snapshot:
            return {
                "status": "success",
                "snapshot": snapshot,
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "success",
                "snapshot": None,
                "message": "No portfolio snapshot available",
                "timestamp": datetime.now().isoformat()
            }

    except Exception as e:
        logger.error(f"Failed to fetch portfolio status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/portfolio/health", tags=["Portfolio"])
async def get_portfolio_health():
    """Get portfolio health status with risk compliance checks.

    Validates portfolio against risk parameters from database.

    Returns:
        Health status with violations and warnings
    """
    try:
        from src.agentic.agents.portfolio_tools import check_portfolio_health
        import json

        # Call the portfolio health tool - invoke() for StructuredTool
        result = check_portfolio_health.invoke({})
        health_data = json.loads(result)

        return {
            "status": "success",
            "health": health_data,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to check portfolio health: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/portfolio/history", tags=["Portfolio"])
async def get_portfolio_history(
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)")
):
    """Get historical portfolio snapshots.

    Args:
        start: Start date for history (optional)
        end: End date for history (optional)

    Returns:
        List of portfolio snapshots
    """
    try:
        from src.common.dao import PortfolioDAO
        dao = PortfolioDAO()
        history = dao.get_snapshot_history(start_date=start, end_date=end)
        dao.close()

        return {
            "status": "success",
            "snapshots": history,
            "count": len(history),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to fetch portfolio history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agent/state/{thread_id}", response_model=AgentStateResponse, tags=["Debug"])
async def get_agent_state(thread_id: str):
    """Get Portfolio Manager agent's conversation state (Improvement #12).

    Useful for debugging and understanding agent behavior.
    Shows conversation history, tool calls, and memory for a given thread.

    Note: Only Portfolio Manager state is exposed via API. Quant Analyst
    is internal and accessed only through Portfolio Manager delegation.

    Args:
        thread_id: Thread ID to inspect

    Returns:
        AgentStateResponse with conversation state
    """
    try:
        manager = get_portfolio_manager()
        state = manager.get_state(thread_id)

        return AgentStateResponse(
            status="success",
            thread_id=thread_id,
            state=state,
            timestamp=datetime.now().isoformat(),
            error=None
        )

    except Exception as e:
        logger.error(f"Failed to retrieve agent state: {e}")
        return AgentStateResponse(
            status="error",
            thread_id=thread_id,
            state=None,
            timestamp=datetime.now().isoformat(),
            error=str(e)
        )


@app.post("/admin/cleanup", response_model=CleanupResponse, tags=["Admin"])
async def trigger_cleanup(dry_run: bool = Query(False, description="Dry run mode (don't actually delete)")):
    """Trigger thread cleanup manually (Improvement #10).

    Deletes expired agent interactions from database based on expires_at timestamp.
    Use dry_run=true to see what would be deleted without actually deleting.

    Args:
        dry_run: If True, only report what would be deleted

    Returns:
        CleanupResponse with deletion stats
    """
    try:
        from src.common.utils.maintenance import cleanup_expired_threads
        result = cleanup_expired_threads(dry_run=dry_run)
        return CleanupResponse(**result)

    except ImportError:
        # Maintenance module not yet implemented
        raise HTTPException(
            status_code=501,
            detail="Maintenance utilities not yet implemented (Module 11 pending)"
        )
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/stats", response_model=StatsResponse, tags=["Admin"])
async def get_database_stats():
    """Get database statistics and table row counts.

    Returns:
        StatsResponse with database size and table statistics
    """
    try:
        from src.common.utils.maintenance import get_database_stats
        result = get_database_stats()
        return StatsResponse(**result)

    except ImportError:
        # Maintenance module not yet implemented
        raise HTTPException(
            status_code=501,
            detail="Maintenance utilities not yet implemented (Module 11 pending)"
        )
    except Exception as e:
        logger.error(f"Stats retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tools", tags=["Info"])
async def list_tools():
    """List available tools for all agents.

    Returns:
        Dict with tool information for Portfolio Manager, Quant Analyst, and Backtester
    """
    return {
        "portfolio_manager_tools": [
            {
                "name": "get_portfolio_status",
                "description": "Fetch current account equity, cash, buying power, positions",
                "returns": "JSON with equity, cash, buying_power, positions count",
                "caching": "5 minutes"
            },
            {
                "name": "get_positions_summary",
                "description": "Get detailed position information with P&L breakdown",
                "returns": "JSON with positions, unrealized P&L, cost basis",
                "caching": "5 minutes"
            },
            {
                "name": "check_portfolio_health",
                "description": "Validate portfolio against risk parameters",
                "returns": "JSON with health status, violations, warnings",
                "caching": "None (always fresh)"
            },
            {
                "name": "delegate_to_quant_analyst",
                "description": "Delegate technical analysis queries to Quant Analyst",
                "parameters": "query (str), symbol (optional)",
                "note": "Internal delegation - Quant tools accessed automatically"
            },
            {
                "name": "delegate_to_backtester",
                "description": "Delegate backtesting queries to Backtester Agent",
                "parameters": "query (str), strategy (optional)",
                "note": "Internal delegation - Backtester tools accessed automatically"
            },
            {
                "name": "fetch_historical_data",
                "description": "Fetch historical market data for a symbol",
                "parameters": "symbol (str), start (str), end (str), timeframe (str)",
                "returns": "JSON with bars data"
            },
            {
                "name": "check_data_availability",
                "description": "Check if historical data exists for symbol and date range",
                "parameters": "symbol (str), start (str), end (str), timeframe (str)",
                "returns": "JSON with availability status, row count, date range"
            }
        ],
        "quant_analyst_tools": [
            {
                "name": "get_market_bars",
                "description": "Fetch OHLCV market data for analysis",
                "parameters": "symbol (str), start (str), end (str), timeframe (str)",
                "returns": "JSON with bars data",
                "note": "Accessed via delegate_to_quant_analyst"
            },
            {
                "name": "get_company_fundamentals",
                "description": "Fetch company fundamental data from Alpha Vantage",
                "parameters": "symbol (str)",
                "returns": "JSON with company overview, financials",
                "note": "Accessed via delegate_to_quant_analyst"
            },
            {
                "name": "save_eod_summary",
                "description": "Save end-of-day analysis summary to database",
                "parameters": "symbol (str), analysis_type (str), summary (str)",
                "note": "Internal tool for analyst observability"
            },
            {
                "name": "save_strategy_result_tool",
                "description": "Save strategy analysis results to database",
                "parameters": "symbol (str), strategy_name (str), result (str)",
                "note": "Internal tool for strategy observability"
            }
        ],
        "backtester_tools": [
            {
                "name": "fetch_backtest_run",
                "description": "Retrieve backtest run metadata by run_id",
                "parameters": "run_id (str)",
                "returns": "JSON with run details",
                "note": "Accessed via delegate_to_backtester"
            },
            {
                "name": "fetch_backtest_trades",
                "description": "Retrieve all trades for a backtest run",
                "parameters": "run_id (str)",
                "returns": "JSON with trade history",
                "note": "Accessed via delegate_to_backtester"
            },
            {
                "name": "fetch_backtest_performance_history",
                "description": "Retrieve performance snapshots for a backtest run",
                "parameters": "run_id (str)",
                "returns": "JSON with equity curve, metrics over time",
                "note": "Accessed via delegate_to_backtester"
            },
            {
                "name": "fetch_historical_bars_for_backtest",
                "description": "Fetch market data for backtesting simulation",
                "parameters": "symbol (str), start (str), end (str), timeframe (str)",
                "returns": "JSON with bars data",
                "note": "Accessed via delegate_to_backtester"
            },
            {
                "name": "save_backtest_run_to_db",
                "description": "Save backtest run results to database",
                "parameters": "run_id (str), metadata (dict)",
                "note": "Internal tool for backtest observability"
            }
        ],
        "architecture": {
            "entry_point": "POST /query",
            "delegation_flow": "Portfolio Manager → Quant Analyst / Backtester (as needed)",
            "note": "All agent interactions go through Portfolio Manager. Delegation happens automatically based on query content."
        }
    }


@app.get("/skills", tags=["Info"])
async def list_skills():
    """List available skills in the system.

    Returns:
        Dict with skill information for Portfolio Manager, Quant Analyst, and Backtester
    """
    return {
        "portfolio_manager_skills": [
            {
                "name": "portfolio-management",
                "description": "Portfolio health analysis, position tracking, risk monitoring, delegation to specialists",
                "path": "src/agents/portfolio/skills/portfolio-management",
                "capabilities": [
                    "Real-time portfolio status (equity, cash, buying power)",
                    "Position summaries with P&L breakdown",
                    "Risk compliance validation",
                    "Historical data fetching",
                    "Data availability checks",
                    "Delegation to Quant Analyst for technical analysis",
                    "Delegation to Backtester for strategy validation"
                ]
            }
        ],
        "quant_analyst_skills": {
            "note": "Accessed via Portfolio Manager delegation (delegate_to_quant_analyst)",
            "level_1_indicators": [
                {
                    "name": "momentum-indicators",
                    "description": "Trend-following indicators for market direction",
                    "path": "src/agents/quant/skills/momentum-indicators",
                    "indicators": [
                        "MACD (Moving Average Convergence Divergence)",
                        "RSI (Relative Strength Index)",
                        "EMA (Exponential Moving Average)"
                    ],
                    "outputs": "MACD value/signal/histogram, RSI percentage, trend signals"
                },
                {
                    "name": "volatility-indicators",
                    "description": "Market volatility and price range analysis",
                    "path": "src/agents/quant/skills/volatility-indicators",
                    "indicators": [
                        "Bollinger Bands (upper/middle/lower)",
                        "Bandwidth percentage",
                        "Volatility classification (low/normal/high/extreme)"
                    ],
                    "outputs": "Band values, bandwidth %, volatility regime, squeeze/expansion signals"
                },
                {
                    "name": "volume-indicators",
                    "description": "Trading volume and flow analysis",
                    "path": "src/agents/quant/skills/volume-indicators",
                    "indicators": [
                        "OBV (On-Balance Volume)",
                        "Volume trend analysis",
                        "Current vs 10-day average volume"
                    ],
                    "outputs": "OBV value, volume trend (increasing/decreasing/stable), volume ratio"
                },
                {
                    "name": "candlestick-patterns",
                    "description": "Price action pattern recognition",
                    "path": "src/agents/quant/skills/candlestick-patterns",
                    "patterns": [
                        "Doji (indecision)",
                        "Hammer (bullish reversal)",
                        "Shooting Star (bearish reversal)",
                        "Engulfing patterns"
                    ],
                    "outputs": "Pattern name, signal type (bullish/bearish/neutral), confidence"
                }
            ],
            "level_2_strategies": [
                {
                    "name": "mean-reversion-strategy",
                    "description": "Complete mean reversion trading strategy with multi-indicator confirmation",
                    "path": "src/agents/quant/skills/mean-reversion-strategy",
                    "components": [
                        "Z-score calculation (price deviation from mean)",
                        "Moving average analysis (20/50 SMA)",
                        "Bollinger Band positioning",
                        "VWAP confirmation",
                        "Combined signal generation"
                    ],
                    "signals": [
                        "STRONG_BUY: Oversold with mean reversion setup",
                        "BUY: Potential upside from mean",
                        "HOLD: Near mean, no clear signal",
                        "SELL: Potential downside to mean",
                        "STRONG_SELL: Overbought with reversion pressure"
                    ],
                    "outputs": "Signal, z-score, percentile rank, VWAP comparison, confidence"
                }
            ]
        },
        "backtester_skills": {
            "note": "Accessed via Portfolio Manager delegation (delegate_to_backtester)",
            "skills": [
                {
                    "name": "backtest-orchestration",
                    "description": "Strategy backtesting workflow coordination",
                    "path": "src/agents/backtester/skills/backtest-orchestration",
                    "capabilities": [
                        "Data preparation and validation",
                        "Strategy parameter configuration",
                        "Simulation execution",
                        "Result aggregation"
                    ]
                },
                {
                    "name": "performance-metrics",
                    "description": "Trading strategy performance analysis",
                    "path": "src/agents/backtester/skills/performance-metrics",
                    "metrics": [
                        "Total return %",
                        "Sharpe ratio",
                        "Maximum drawdown",
                        "Win rate",
                        "Profit factor",
                        "Average win/loss ratio"
                    ]
                },
                {
                    "name": "simulation-engine",
                    "description": "Historical trade simulation with realistic execution",
                    "path": "src/agents/backtester/skills/simulation-engine",
                    "features": [
                        "Order execution simulation",
                        "Position tracking",
                        "Equity curve generation",
                        "Trade log creation"
                    ]
                }
            ]
        },
        "architecture": {
            "entry_point": "POST /query",
            "workflow": "User → Portfolio Manager → [Quant Analyst | Backtester] (auto delegation)",
            "skill_hierarchy": {
                "level_0": "Portfolio Manager (orchestration, risk management)",
                "level_1": "Quant Analyst indicators (MACD, RSI, Bollinger Bands, etc.)",
                "level_2": "Quant strategies (Mean Reversion, etc.)",
                "level_3": "Backtester (strategy validation, performance analysis)"
            },
            "data_flow": "Market Data → ETL (computed indicators) → Agents → Analysis → Portfolio Manager → User"
        }
    }


@app.get("/ingestion/status", response_model=IngestionStatusResponse, tags=["Ingestion"])
async def get_ingestion_status():
    """Get real-time status of the ingestion pipeline.

    Returns status of:
    - Data stream (running/stopped, symbols)
    - Trade cache (size, last flush)
    - ETL scheduler (running/stopped, last run)

    Returns:
        IngestionStatusResponse with pipeline component statuses
    """
    try:
        from src.common.data_gatherer.trade_cache import get_cache

        # Data stream status
        data_stream_status = {
            "enabled": config.get("data_stream.enabled", default=False),
            "running": background_tasks['data_stream'] is not None and not background_tasks['data_stream'].done(),
            "auto_start": config.get("data_stream.auto_start", default=False),
            "feed": config.get("data_stream.feed", default="iex")
        }

        # Cache status
        cache = get_cache()
        cache_size = len(cache._cache) if hasattr(cache, '_cache') else 0
        cache_max_size = config.get("cache.max_size", default=100000)
        cache_status = {
            "enabled": config.get("cache.enabled", default=True),
            "current_size": cache_size,
            "max_size": cache_max_size,
            "utilization_percent": round((cache_size / cache_max_size) * 100, 2) if cache_max_size > 0 else 0,
            "batch_interval_minutes": config.get("cache.batch_interval_minutes", default=5),
            "last_flush": getattr(cache, '_last_flush', None).isoformat() if hasattr(cache, '_last_flush') and cache._last_flush else None
        }

        # ETL status (auto-runs with bar ingestion)
        etl_status = {
            "enabled": config.get("etl.enabled", default=True),
            "mode": "auto-run",
            "description": "Indicators computed automatically when bars are saved",
            "timeframes": config.get("etl.timeframes", default=["1Min", "1Hour", "1Day"]),
            "lookback_days": config.get("etl.lookback_days", default=60)
        }

        return IngestionStatusResponse(
            data_stream=data_stream_status,
            cache=cache_status,
            etl=etl_status,
            timestamp=datetime.now().isoformat()
        )

    except Exception as e:
        logger.error(f"Failed to get ingestion status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingestion/trigger-etl", response_model=ETLTriggerResponse, tags=["Ingestion"])
async def trigger_etl():
    """Manually trigger ETL pipeline to compute indicators.

    Runs ETL for all watchlist symbols across configured timeframes.
    This can take several minutes depending on data volume.

    Returns:
        ETLTriggerResponse with computation results
    """
    try:
        from src.common.etl.pipeline import IndicatorsETL

        logger.info("⚙️ Manually triggered ETL...")
        etl = IndicatorsETL()
        result = etl.run_for_watchlist()
        etl.close()

        logger.info(f"✅ ETL complete: {result['total_rows']} indicators computed")

        return ETLTriggerResponse(
            status="success",
            message=f"ETL completed successfully for {len(result['symbols'])} symbols",
            total_rows=result['total_rows'],
            symbols=result['symbols'],
            timestamp=datetime.now().isoformat(),
            error=None
        )

    except Exception as e:
        logger.error(f"❌ Manual ETL failed: {e}", exc_info=True)
        return ETLTriggerResponse(
            status="error",
            message="ETL execution failed",
            total_rows=None,
            symbols=None,
            timestamp=datetime.now().isoformat(),
            error=str(e)
        )


@app.post("/ingestion/flush-cache", response_model=CacheFlushResponse, tags=["Ingestion"])
async def flush_cache():
    """Manually flush the trade cache to database.

    Forces immediate write of all cached trades to the database.
    Normally cache flushes automatically based on time/size triggers.

    Returns:
        CacheFlushResponse with flush results
    """
    try:
        from src.common.data_gatherer.trade_cache import get_cache
        from src.common.data_gatherer.db_stream_handlers import flush_cache_to_db

        # Get current cache size
        cache = get_cache()
        cache_size = len(cache._cache) if hasattr(cache, '_cache') else 0

        if cache_size == 0:
            return CacheFlushResponse(
                status="success",
                message="Cache is empty, nothing to flush",
                trades_flushed=0,
                timestamp=datetime.now().isoformat(),
                error=None
            )

        logger.info(f"📦 Manually flushing cache ({cache_size} trades)...")
        await flush_cache_to_db()

        return CacheFlushResponse(
            status="success",
            message=f"Successfully flushed {cache_size} trades to database",
            trades_flushed=cache_size,
            timestamp=datetime.now().isoformat(),
            error=None
        )

    except Exception as e:
        logger.error(f"❌ Cache flush failed: {e}", exc_info=True)
        return CacheFlushResponse(
            status="error",
            message="Cache flush failed",
            trades_flushed=None,
            timestamp=datetime.now().isoformat(),
            error=str(e)
        )


if __name__ == "__main__":
    """Run FastAPI server with uvicorn."""
    import uvicorn

    print("="*70)
    print("Agentic Portfolio Manager API Server")
    print("="*70)
    print("\nArchitecture: Single entry point via Portfolio Manager")
    print("  - All queries go through POST /query")
    print("  - Portfolio Manager delegates to Quant Analyst internally")
    print("  - Middleware enforces risk limits and market hours")
    print("\nCore Endpoints:")
    print("  GET  /                     - API information")
    print("  GET  /health               - Basic health check")
    print("  GET  /health/detailed      - Comprehensive system health")
    print("  POST /query                - Main entry point (all queries)")
    print("\nPortfolio Endpoints:")
    print("  GET  /portfolio/status     - Current portfolio snapshot")
    print("  GET  /portfolio/health     - Risk compliance check")
    print("  GET  /portfolio/history    - Historical snapshots")
    print("\nDebug/Admin Endpoints:")
    print("  GET  /agent/state/{id}     - Inspect agent conversation state")
    print("  POST /admin/cleanup        - Cleanup expired threads")
    print("  GET  /admin/stats          - Database statistics")
    print("\nInfo Endpoints:")
    print("  GET  /tools                - List available tools")
    print("  GET  /skills               - List available skills")
    print("\nIngestion Pipeline Endpoints:")
    print("  GET  /ingestion/status     - Real-time pipeline status")
    print("  POST /ingestion/trigger-etl- Manually trigger ETL")
    print("  POST /ingestion/flush-cache- Manually flush trade cache")
    print("\nServer running at: http://localhost:8000")
    print("API docs at: http://localhost:8000/docs")
    print("ReDoc at: http://localhost:8000/redoc")
    print("\nExample queries:")
    print('  # Portfolio status:')
    print('  curl -X POST "http://localhost:8000/query" \\')
    print('       -H "Content-Type: application/json" \\')
    print('       -d \'{"query": "What is my portfolio status?"}\'')
    print()
    print('  # Technical analysis (delegates to Quant internally):')
    print('  curl -X POST "http://localhost:8000/query" \\')
    print('       -H "Content-Type: application/json" \\')
    print('       -d \'{"query": "Should I buy AAPL? Run technical analysis."}\'')
    print("="*70)

    uvicorn.run(
        "src.agentic.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Set to False in production
        log_level="info",
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                    "datefmt": "%H:%M:%S"
                }
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout"
                }
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": "INFO"},
                "uvicorn.error": {"level": "INFO"},
                "uvicorn.access": {"handlers": ["default"], "level": "INFO"},
                "watchfiles": {"handlers": ["default"], "level": "WARNING"}  # Suppress watchfiles debug logs
            }
        }
    )
