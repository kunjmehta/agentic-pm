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
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

from src.agents.portfolio import PortfolioManager
from src.utils import get_logger

logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Agentic Portfolio Manager API",
    description="Portfolio Manager Agent with Risk Management and Technical Analysis Delegation",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
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


def get_portfolio_manager() -> PortfolioManager:
    """Get or create Portfolio Manager instance."""
    global portfolio_manager
    if portfolio_manager is None:
        portfolio_manager = PortfolioManager(
            model="gpt-4o-mini",
            backtest_mode=False  # Set to False in production for middleware enforcement
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
                "model": "gpt-4o-mini",
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
        from src.dao import PortfolioDAO
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
        from src.utils import secrets
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
        from src.utils import secrets
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


@app.get("/portfolio/status", tags=["Portfolio"])
async def get_portfolio_status():
    """Get current portfolio status from database.

    Returns latest snapshot with equity, cash, positions, and P&L.

    Returns:
        Latest portfolio snapshot or error
    """
    try:
        from src.dao import PortfolioDAO
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
        from src.agents.portfolio_tools import check_portfolio_health
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
        from src.dao import PortfolioDAO
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
        from src.utils.maintenance import cleanup_expired_threads
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
        from src.utils.maintenance import get_database_stats
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
    """List available tools for Portfolio Manager.

    Returns:
        Dict with tool information
    """
    return {
        "portfolio_manager_tools": [
            {
                "name": "get_portfolio_status",
                "description": "Fetch current account equity, cash, buying power, positions",
                "agent": "portfolio"
            },
            {
                "name": "get_positions_summary",
                "description": "Get detailed position information with P&L breakdown",
                "agent": "portfolio"
            },
            {
                "name": "check_portfolio_health",
                "description": "Validate portfolio against risk parameters",
                "agent": "portfolio"
            },
            {
                "name": "delegate_to_quant_analyst",
                "description": "Delegate technical analysis to Quant Analyst",
                "agent": "portfolio",
                "note": "Quant Analyst tools accessed internally via delegation"
            }
        ],
        "note": "All queries should go through POST /query endpoint. Portfolio Manager handles delegation automatically."
    }


@app.get("/skills", tags=["Info"])
async def list_skills():
    """List available skills in the system.

    Returns:
        Dict with skill information for both agents
    """
    return {
        "portfolio_manager_skills": [
            {
                "name": "portfolio-management",
                "description": "Portfolio health analysis, historical performance, risk monitoring",
                "path": "src/agents/portfolio/skills/portfolio-management",
                "functions": [
                    "get_portfolio_status()",
                    "get_positions_summary()",
                    "check_portfolio_health()",
                    "delegate_to_quant_analyst()"
                ]
            }
        ],
        "quant_analyst_skills": {
            "note": "Accessed internally via Portfolio Manager delegation",
            "level_1_indicators": [
                {
                    "name": "momentum-indicators",
                    "description": "MACD, RSI, EMA calculations",
                    "path": "src/agents/quant/skills/momentum-indicators"
                },
                {
                    "name": "volatility-indicators",
                    "description": "Bollinger Bands, ATR",
                    "path": "src/agents/quant/skills/volatility-indicators"
                },
                {
                    "name": "volume-indicators",
                    "description": "OBV, volume flow analysis",
                    "path": "src/agents/quant/skills/volume-indicators"
                },
                {
                    "name": "candlestick-patterns",
                    "description": "Pattern recognition (doji, hammer, etc.)",
                    "path": "src/agents/quant/skills/candlestick-patterns"
                }
            ],
            "level_2_strategies": [
                {
                    "name": "mean-reversion-strategy",
                    "description": "Complete mean reversion analysis with VWAP confirmation",
                    "path": "src/agents/quant/skills/mean-reversion-strategy",
                    "features": ["z-score", "moving averages", "Bollinger Bands", "VWAP confirmation"]
                }
            ]
        },
        "architecture": "Single entry point via Portfolio Manager (POST /query). Quant skills accessed via internal delegation."
    }


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
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Set to False in production
        log_level="info"
    )
