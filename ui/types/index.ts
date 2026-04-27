// ── API Presets ──────────────────────────────────────────────────────────────

export type ApiPreset = 'langgraph' | 'agentic' | 'semiAuto' | 'custom';

export const API_PRESETS: Record<ApiPreset, string> = {
  langgraph: 'http://localhost:8001/v1',
  agentic:   'http://localhost:8000',
  semiAuto:  'http://localhost:8000/v1',
  custom:    '',
};

// ── Tasks ────────────────────────────────────────────────────────────────────

export interface Task {
  task_id?: string;
  function_name?: string;
  params?: Record<string, unknown>;
  priority?: number;
  depends_on?: string[];
}

// ── Execution ────────────────────────────────────────────────────────────────

export interface ExecutionResult {
  task_id: string;
  function_name: string;
  status: 'success' | 'error' | 'skipped';
  result?: unknown;
  error?: string;
  duration_ms?: number;
}

// ── Trades ───────────────────────────────────────────────────────────────────

export interface Trade {
  status?: string;
  entry_date?: string;
  timestamp?: string;
  entry_time?: string;
  entry_price?: number;
  price?: number;
  exit_date?: string;
  exit_time?: string;
  exit_price?: number;
  quantity?: number;
  side?: string;
  entry_signal?: Record<string, unknown>;
  exit_reason?: string;
  pnl?: number;
  pnl_pct?: number;
}

export interface BacktestMetrics {
  total_return_pct?: number;
  total_return_dollars?: number;
  sharpe_ratio?: number;
  max_drawdown_pct?: number;
  max_drawdown_dollars?: number;
  win_rate?: number;
}

export interface BacktestResult {
  task_id: string;
  function_name: string;
  status: string;
  result: {
    strategy?: string;
    strategy_name?: string;
    symbol?: string;
    ticker?: string;
    trades?: Trade[];
    metrics?: BacktestMetrics;
    final_capital?: number;
  };
}

// ── Portfolio ────────────────────────────────────────────────────────────────

export interface HealthResult {
  overall_status?: string;
  status?: string;
  health_status?: string;
  reason?: string;
  description?: string;
  message?: string;
  equity?: number;
  cash?: number;
  buying_power?: number;
  position_count?: number;
  risk_score?: number;
  max_drawdown?: number;
  daily_pnl?: number;
}

export interface PortfolioStatResult {
  equity?: number;
  cash?: number;
  unrealized_pl?: number;
  realized_pl?: number;
  daily_change?: number;
  total_return?: number;
  sharpe_ratio?: number;
  max_drawdown?: number;
  win_rate?: number;
  position_count?: number;
}

// ── Indicators ───────────────────────────────────────────────────────────────

export interface MomentumIndicators {
  rsi?: number;
  macd_value?: number;
  macd_signal?: number;
  macd_histogram?: number;
}

export interface VolatilityIndicators {
  bb_upper?: number;
  bb_lower?: number;
  bb_middle?: number;
  atr?: number;
  z_score?: number;
}

export interface VolumeIndicators {
  obv?: number;
  volume_trend?: string;
  vwap?: number;
}

export interface IndicatorRecord {
  symbol?: string;
  timestamp?: string;
  timeframe?: string;
  momentum?: MomentumIndicators;
  volatility?: VolatilityIndicators;
  volume?: VolumeIndicators;
}

// ── Task preview (HITL) ──────────────────────────────────────────────────────

export interface TaskPreviewData {
  thread_id: string;
  portfolio_reasoning?: string;
  quant_reasoning?: string;
  backtester_reasoning?: string;
  order_reasoning?: string;
  pm_review_notes?: string;
  portfolio_tasks?: Task[];
  quant_tasks?: Task[];
  backtester_tasks?: Task[];
  order_tasks?: Task[];
}

// ── Message ──────────────────────────────────────────────────────────────────

export interface ThinkingBlock {
  agent: string;
  content: string;
  taskCount?: number;
}

export type MessageContent =
  | { type: 'thinking'; block: ThinkingBlock }
  | { type: 'tool_badge'; name: string }
  | { type: 'text'; markdown: string }
  | { type: 'error'; msg: string }
  | { type: 'task_preview'; data: TaskPreviewData }
  | { type: 'health'; result: ExecutionResult }
  | { type: 'portfolio_stats'; result: ExecutionResult }
  | { type: 'trades'; results: BacktestResult[] }
  | { type: 'telemetry'; results: ExecutionResult[] }
  | { type: 'exec_summary'; results: ExecutionResult[] }
  | { type: 'pending_notice' };

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: MessageContent[];
  isStreaming?: boolean;
}

// ── API response shapes ──────────────────────────────────────────────────────

export interface SemiAutoResponse {
  final_response: string;
  execution_results: ExecutionResult[];
  tasks_executed: number;
  intent?: string;
  symbol?: string;
}

export interface ConversationTurn {
  turn_number: number;
  query: string;
  timestamp: string;
  status: string;
  intent?: string;
  symbol?: string;
  final_response?: string;
  portfolio_reasoning?: string;
  quant_reasoning?: string;
  backtester_reasoning?: string;
  execution_results?: ExecutionResult[];
  pm_review_notes?: string;
}
