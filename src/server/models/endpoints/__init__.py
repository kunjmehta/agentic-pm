"""endpoints sub-package — re-exports all public endpoint response model names.

Import from this package exactly as you would from the old flat endpoints.py:

    from src.server.models.endpoints import WatchlistResponse, OrderResponse
"""

from src.server.models.endpoints.admin import AdminStatsResponse, CleanupResponse
from src.server.models.endpoints.agent import (
    AgentStateResponse,
    ConversationResponse,
    RegistryResponse,
    RejectResponse,
)
from src.server.models.endpoints.analyst import (
    AnalystSymbolsResponse,
    EODSummariesResponse,
    LatestEODResponse,
    RecentEODsResponse,
)
from src.server.models.endpoints.backtest import (
    BacktestPerformanceResponse,
    BacktestRunResponse,
    BacktestRunsResponse,
    BacktestTradesResponse,
)
from src.server.models.endpoints.common import IndicatorRecord, OHLCVBar, TradeRecord
from src.server.models.endpoints.config import (
    ConfigReloadResponse,
    ConfigResponse,
    ConfigSectionResponse,
    RootResponse,
    WatchlistEntryResponse,
)
from src.server.models.endpoints.fundamentals import (
    BalanceSheetResponse,
    CashFlowResponse,
    CompanyOverviewResponse,
    DividendsResponse,
    EarningsResponse,
    FundamentalsListResponse,
    IncomeStatementResponse,
)
from src.server.models.endpoints.health import (
    ComponentStatus,
    DetailedHealthResponse,
    HealthResponse,
)
from src.server.models.endpoints.ingestion import (
    DataStreamInfo,
    FlushCacheResponse,
    IngestionStatusResponse,
    TriggerETLResponse,
)
from src.server.models.endpoints.market import (
    BarsResponse,
    IndicatorsResponse,
    IntradayStatsResponse,
    LatestBarResponse,
    TradesResponse,
    WatchlistMemberResponse,
    WatchlistResponse,
)
from src.server.models.endpoints.orders import (
    OpenOrdersResponse,
    OrderCancelResponse,
    OrderResponse,
    ScalePositionResponse,
    StrategySignalExecutionResponse,
)
from src.server.models.endpoints.portfolio import (
    PortfolioHealthResponse,
    PortfolioHistoryResponse,
)
from src.server.models.endpoints.strategy import (
    ActionableSignalsResponse,
    LatestSignalResponse,
    PendingSignalsResponse,
    RecentSignalsResponse,
    SignalModifyRequest,
    SignalModifyResponse,
    SignalRejectRequest,
    SignalReviewResponse,
    StrategyPerformanceResponse,
)

__all__ = [
    # common
    "OHLCVBar",
    "TradeRecord",
    "IndicatorRecord",
    # health
    "ComponentStatus",
    "HealthResponse",
    "DetailedHealthResponse",
    # portfolio
    "PortfolioHealthResponse",
    "PortfolioHistoryResponse",
    # admin
    "CleanupResponse",
    "AdminStatsResponse",
    # ingestion
    "DataStreamInfo",
    "IngestionStatusResponse",
    "TriggerETLResponse",
    "FlushCacheResponse",
    # agent / HITL
    "RejectResponse",
    "ConversationResponse",
    "AgentStateResponse",
    "RegistryResponse",
    # market
    "WatchlistResponse",
    "WatchlistMemberResponse",
    "BarsResponse",
    "LatestBarResponse",
    "TradesResponse",
    "IndicatorsResponse",
    "IntradayStatsResponse",
    # fundamentals
    "FundamentalsListResponse",
    "CompanyOverviewResponse",
    "DividendsResponse",
    "EarningsResponse",
    "IncomeStatementResponse",
    "BalanceSheetResponse",
    "CashFlowResponse",
    # analyst
    "AnalystSymbolsResponse",
    "EODSummariesResponse",
    "LatestEODResponse",
    "RecentEODsResponse",
    # strategy
    "ActionableSignalsResponse",
    "StrategyPerformanceResponse",
    "LatestSignalResponse",
    "RecentSignalsResponse",
    "PendingSignalsResponse",
    "SignalReviewResponse",
    "SignalRejectRequest",
    "SignalModifyRequest",
    "SignalModifyResponse",
    # backtest
    "BacktestRunsResponse",
    "BacktestRunResponse",
    "BacktestTradesResponse",
    "BacktestPerformanceResponse",
    # orders
    "OrderResponse",
    "ScalePositionResponse",
    "StrategySignalExecutionResponse",
    "OrderCancelResponse",
    "OpenOrdersResponse",
    # config + root
    "ConfigResponse",
    "ConfigSectionResponse",
    "WatchlistEntryResponse",
    "ConfigReloadResponse",
    "RootResponse",
]
