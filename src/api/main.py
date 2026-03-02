"""FastAPI server for Quant Analyst agent.

Provides REST API for:
- Natural language queries to the Quant Analyst
- Strategy execution (mean reversion, etc.)
- Tool access (market data, fundamentals)

Updated to use natural language invoke() interface.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

from src.agents.quant.analyst import QuantAnalyst
from src.utils import get_logger

logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Agentic Trader API",
    description="Quantitative Analysis Agent for Technical Trading - Natural Language Interface",
    version="1.0.0",
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

# Initialize analyst (singleton)
analyst = None


def get_analyst() -> QuantAnalyst:
    """Get or create analyst instance."""
    global analyst
    if analyst is None:
        analyst = QuantAnalyst(
            model="gpt-4o-mini",  # Updated to use latest model
            backtest_mode=False  # Set to False in production
        )
        logger.info("QuantAnalyst initialized")
    return analyst


# Request/Response models
class AnalysisRequest(BaseModel):
    """Request model for natural language analysis."""
    query: str = Field(..., description="Natural language query for the agent", min_length=1)
    apply_middleware: bool = Field(True, description="Whether to apply middleware stack")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Run mean reversion strategy on AAPL",
                "apply_middleware": True
            }
        }


class AnalysisResponse(BaseModel):
    """Response model for analysis."""
    query: str = Field(..., description="Original query")
    response: str = Field(..., description="Agent response")
    timestamp: str = Field(..., description="ISO timestamp of analysis")
    model: str = Field(..., description="LLM model used")
    status: str = Field(..., description="Status: success | error")
    error: Optional[str] = Field(None, description="Error message if status is error")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Run mean reversion strategy on AAPL",
                "response": "Mean Reversion Analysis for AAPL: Signal: BUY, Confidence: 0.85...",
                "timestamp": "2026-02-22T18:00:00",
                "model": "gpt-4o-mini",
                "status": "success",
                "error": None
            }
        }


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str = Field(..., description="healthy | degraded | unhealthy")
    timestamp: str = Field(..., description="ISO timestamp of health check")
    components: Dict[str, str] = Field(..., description="Component health status")
    version: str = Field(..., description="API version")


# Routes
@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Agentic Trader API",
        "version": "1.0.0",
        "description": "Quantitative Analysis Agent with Natural Language Interface",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint.

    Returns:
        HealthResponse with component status
    """
    components = {}

    # Check database
    try:
        from src.dao import AlpacaDAO
        dao = AlpacaDAO()
        dao.close()
        components["database"] = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        components["database"] = f"unhealthy: {str(e)}"

    # Check agent
    try:
        agent = get_analyst()
        components["agent"] = "healthy"
    except Exception as e:
        logger.error(f"Agent health check failed: {e}")
        components["agent"] = f"unhealthy: {str(e)}"

    # Determine overall status
    unhealthy_count = sum(1 for v in components.values() if "unhealthy" in v)
    if unhealthy_count == 0:
        overall_status = "healthy"
    elif unhealthy_count < len(components):
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now().isoformat(),
        components=components,
        version="1.0.0"
    )


@app.post("/analyze", response_model=AnalysisResponse, tags=["Analysis"])
async def analyze(request: AnalysisRequest):
    """Execute quantitative analysis based on natural language query.

    Examples:
    - "Run mean reversion strategy on AAPL"
    - "Get market data for TSLA from the last 60 minutes"
    - "Analyze MSFT using technical indicators"
    - "What is the RSI for NVDA and what does it indicate?"

    Args:
        request: AnalysisRequest with natural language query

    Returns:
        AnalysisResponse with agent analysis

    Raises:
        HTTPException: If analysis fails or market is closed
    """
    logger.info(f"Received analysis request: {request.query}")

    try:
        # Get analyst agent
        agent = get_analyst()

        # Execute natural language query
        result = agent.invoke(
            query=request.query,
            apply_middleware=request.apply_middleware
        )

        return AnalysisResponse(
            query=result["query"],
            response=result["response"],
            timestamp=result["timestamp"],
            model=result["model"],
            status="success",
            error=None
        )

    except RuntimeError as e:
        # Market hours check failure
        logger.warning(f"Analysis blocked: {e}")
        raise HTTPException(status_code=403, detail=str(e))

    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        return AnalysisResponse(
            query=request.query,
            response="",
            timestamp=datetime.now().isoformat(),
            model="unknown",
            status="error",
            error=str(e)
        )


@app.get("/status/{symbol}", tags=["Info"])
async def get_status(symbol: str):
    """Get latest analysis status for a symbol.

    Args:
        symbol: Stock ticker

    Returns:
        Latest strategy results and EOD summaries from database
    """
    try:
        from src.dao import AnalystDAO, StrategyDAO

        # Get EOD summary
        analyst_dao = AnalystDAO()
        latest_eod = analyst_dao.get_latest_eod(symbol)
        analyst_dao.close()

        # Get strategy results
        strategy_dao = StrategyDAO()
        latest_strategy = strategy_dao.get_latest_signal(symbol, "mean-reversion")
        strategy_dao.close()

        return {
            "symbol": symbol,
            "has_eod": latest_eod is not None,
            "has_strategy": latest_strategy is not None,
            "latest_eod": {
                "timestamp": latest_eod["timestamp"].isoformat() if latest_eod and hasattr(latest_eod["timestamp"], "isoformat") else None,
                "summary": latest_eod["summary_text"][:200] + "..." if latest_eod and len(latest_eod["summary_text"]) > 200 else (latest_eod["summary_text"] if latest_eod else None),
                "signals": latest_eod["signals"] if latest_eod else None
            } if latest_eod else None,
            "latest_strategy": {
                "timestamp": latest_strategy["timestamp"].isoformat() if latest_strategy and hasattr(latest_strategy["timestamp"], "isoformat") else None,
                "action": latest_strategy["action"] if latest_strategy else None,
                "confidence": float(latest_strategy["confidence"]) if latest_strategy else None,
                "current_price": float(latest_strategy["current_price"]) if latest_strategy else None
            } if latest_strategy else None
        }

    except Exception as e:
        logger.error(f"Failed to fetch status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch status: {e}")


@app.get("/tools", tags=["Info"])
async def list_tools():
    """List available tools for the agent.

    Returns:
        Dict with tool information
    """
    return {
        "tools": [
            {
                "name": "get_market_bars",
                "description": "Fetch recent market OHLCV data",
                "parameters": ["symbol", "minutes"]
            },
            {
                "name": "get_company_fundamentals",
                "description": "Get company overview and fundamentals",
                "parameters": ["symbol"]
            },
            {
                "name": "save_eod_summary",
                "description": "Save end-of-day analysis summary",
                "parameters": ["symbol", "indicators", "summary_text", "signals", "thought_trace", "model_used"]
            },
            {
                "name": "save_strategy_result_tool",
                "description": "Save trading strategy results",
                "parameters": ["symbol", "strategy_name", "result_json", "thought_trace", "model_used"]
            }
        ]
    }


@app.get("/skills", tags=["Info"])
async def list_skills():
    """List available skills for the agent.

    Returns:
        Dict with skill information
    """
    return {
        "skills": {
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
        }
    }


if __name__ == "__main__":
    """Run FastAPI server with uvicorn."""
    import uvicorn

    print("="*60)
    print("Agentic Trader API Server")
    print("="*60)
    print("\nEndpoints:")
    print("  GET  /          - API information")
    print("  GET  /health    - Health check with component status")
    print("  POST /analyze   - Natural language analysis (main endpoint)")
    print("  GET  /status/{symbol} - Get latest analysis for symbol")
    print("  GET  /tools     - List available tools")
    print("  GET  /skills    - List available skills")
    print("\nServer running at: http://localhost:8000")
    print("API docs at: http://localhost:8000/docs")
    print("ReDoc at: http://localhost:8000/redoc")
    print("\nExample query:")
    print('  curl -X POST "http://localhost:8000/analyze" \\')
    print('       -H "Content-Type: application/json" \\')
    print('       -d \'{"query": "Run mean reversion strategy on AAPL"}\'')
    print("="*60)

    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Set to False in production
        log_level="info"
    )
