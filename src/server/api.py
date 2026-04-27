"""FastAPI server for the trading multi-agent portfolio manager.

Runs on port 8000.  All endpoint logic lives in src/server/routers/*.

Two-phase HITL flow:
  POST /v1/query              -> reasoning nodes -> TaskPreviewResponse (interrupt)
  POST /v1/approve/{id}       -> resume graph   -> SemiAutoResponse
  POST /v1/reject/{id}        -> cancel pending execution

Order execution endpoints (src/server/routers/orders.py):
  POST /v1/orders/execute     -> place market or limit order
  POST /v1/orders/scale       -> scale position to target portfolio %
  POST /v1/orders/signal      -> execute strategy signal (buy/sell/hold)
  POST /v1/orders/close/{sym} -> liquidate a position
  DELETE /v1/orders/{id}      -> cancel an open order

Configuration endpoints (src/server/routers/config.py):
  GET  /v1/config             -> full configuration
  GET  /v1/config/ui          -> UI-formatted configuration
  PUT  /v1/config/ui          -> update configuration from UI format
  GET  /v1/config/{section}   -> specific config section
  PUT  /v1/config/{section}   -> update config section
  POST /v1/config/watchlist/add         -> add ticker with strategies
  DELETE /v1/config/watchlist/{symbol}  -> remove ticker from watchlist

Streaming / real-time endpoints:
  GET /v1/telemetry/stream/{thread_id}  -> SSE stream of execution telemetry
  WS  /v1/portfolio/ws                  -> WebSocket for real-time portfolio updates
  WS  /v1/redis/stream/{symbol}         -> WebSocket Redis stream proxy (market data)
  GET /v1/redis/health                  -> Redis connection health check

DAO read endpoints:
  GET /v1/market/...          AlpacaDAO (bars, quotes, trades, snapshots)
  GET /v1/fundamentals/...    AlphaVantageDAO (income, balance, earnings, etc.)
  GET /v1/analyst/...         AnalysisDAO (EOD analyst summaries)
  GET /v1/strategy/...        AnalysisDAO (strategy signals and results)
  GET /v1/backtest/...        BacktestDAO (backtest runs, metrics, equity curves)
  GET /v1/portfolio/...       Portfolio positions and history
Utility endpoints:
  GET /v1/health              -> liveness check
  GET /v1/registry            -> list registered agent functions
  POST /v1/ingestion/...      -> trigger data ingestion pipeline
  /v1/sandbox/...             -> Daytona cloud sandbox (Monaco editor + quant agent)
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.server.lifespan import lifespan
from src.server.routers.health import router as health_router
from src.server.routers.agent import router as agent_router
from src.server.routers.portfolio import router as portfolio_router
from src.server.routers.admin import router as admin_router
from src.server.routers.ingestion import router as ingestion_router
from src.server.routers.market import router as market_router
from src.server.routers.fundamentals import router as fundamentals_router
from src.server.routers.analyst import router as analyst_router
from src.server.routers.strategy import router as strategy_router
from src.server.routers.backtest import router as backtest_router
from src.server.routers.orders import router as orders_router
from src.server.routers.config import router as config_router
from src.server.routers.telemetry import router as telemetry_router
from src.server.routers.redis_ws_proxy import router as redis_ws_router
from src.server.routers.sandbox_router import router as sandbox_router
from src.common.utils import config as app_config
from src.server.models.endpoints import RootResponse

# -- App -----------------------------------------------------------------------

app = FastAPI(
    title="Semi-Auto Portfolio Manager",
    description=(
        "LangGraph multi-agent system with reasoning agents, task queues, "
        "human-in-the-loop approval, and parallel function execution."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Routers -------------------------------------------------------------------

app.include_router(health_router)
app.include_router(agent_router)
app.include_router(portfolio_router)
app.include_router(admin_router)
app.include_router(ingestion_router)
app.include_router(market_router)
app.include_router(fundamentals_router)
app.include_router(analyst_router)
app.include_router(strategy_router)
app.include_router(backtest_router)
app.include_router(orders_router)
app.include_router(config_router)
app.include_router(telemetry_router)
app.include_router(redis_ws_router)
app.include_router(sandbox_router)


# -- Root ----------------------------------------------------------------------


@app.get("/", response_model=RootResponse)
async def root():
    """API info."""
    return {
        "name": "Semi-Auto Portfolio Manager",
        "version": "1.0.0",
        "description": "LangGraph multi-agent with reasoning agents + HITL task approval",
        "port": app_config.get("graph_api.port", 8001),
        "endpoints": {
            "POST /v1/query": "Phase 1: reasoning -> HITL interrupt (returns task preview)",
            "POST /v1/approve/{thread_id}": "Phase 2: approve tasks -> execute -> synthesize",
            "POST /v1/reject/{thread_id}": "Cancel pending execution",
            "GET /v1/registry": "List registered functions",
            "GET /v1/health": "Liveness check",
            "POST /v1/orders/execute": "Place a market or limit order directly",
            "POST /v1/orders/scale": "Scale a position to a target portfolio %",
            "POST /v1/orders/signal": "Execute a strategy signal (buy/sell/hold)",
            "POST /v1/orders/close/{symbol}": "Close (liquidate) a position",
            "DELETE /v1/orders/{order_id}": "Cancel an open order",
            "GET /v1/config": "Get full configuration",
            "GET /v1/config/ui": "Get UI-formatted configuration (watchlist/strategies as arrays)",
            "PUT /v1/config/ui": "Update configuration from UI format",
            "GET /v1/config/{section}": "Get specific config section",
            "PUT /v1/config/{section}": "Update config section",
            "POST /v1/config/watchlist/add": "Add ticker to watchlist with strategies",
            "DELETE /v1/config/watchlist/{symbol}": "Remove ticker from watchlist",
            "GET /v1/telemetry/stream/{thread_id}": "SSE stream of execution telemetry",
            "WS /v1/portfolio/ws": "WebSocket for real-time portfolio updates",
            "WS /v1/redis/stream/{symbol}": "WebSocket for Redis Stream proxy (real-time market data)",
            "GET /v1/redis/health": "Redis connection health check",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
