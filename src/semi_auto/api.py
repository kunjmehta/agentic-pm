"""FastAPI server for the semi-auto multi-agent portfolio manager.

Runs on port 8000.  All endpoint logic lives in src/semi_auto/routers/*.

Two-phase HITL flow:
  POST /v1/query         -> runs reasoning nodes -> returns TaskPreviewResponse
  POST /v1/approve/{id}  -> resumes graph -> returns SemiAutoResponse
  POST /v1/reject/{id}   -> cancels pending execution

DAO read endpoints:
  GET /v1/market/...        AlpacaDAO
  GET /v1/fundamentals/...  AlphaVantageDAO
  GET /v1/analyst/...       AnalystDAO
  GET /v1/strategy/...      StrategyDAO
  GET /v1/backtest/...      BacktestDAO
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.semi_auto.lifespan import lifespan
from src.semi_auto.routers.health import router as health_router
from src.semi_auto.routers.agent import router as agent_router
from src.semi_auto.routers.portfolio import router as portfolio_router
from src.semi_auto.routers.admin import router as admin_router
from src.semi_auto.routers.ingestion import router as ingestion_router
from src.semi_auto.routers.market import router as market_router
from src.semi_auto.routers.fundamentals import router as fundamentals_router
from src.semi_auto.routers.analyst import router as analyst_router
from src.semi_auto.routers.strategy import router as strategy_router
from src.semi_auto.routers.backtest import router as backtest_router
from src.common.utils import config as app_config
from src.semi_auto.models.endpoints import RootResponse

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
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
