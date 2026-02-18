# Agentic Portfolio Manager - Final Design Document

## 1. System Overview

### 1.1 Purpose

An autonomous multi-agent system for **zero-user portfolio management** that analyzes market data, executes trades, and manages investment portfolios using AI agents with minimal human intervention.

### 1.2 Core Principles

* **Autonomous Operation:** Runs on scheduled jobs with minimal human oversight.
* **Modular Architecture:** Each agent has a single, well-defined responsibility.
* **Event-Driven Communication:** Agents communicate through DuckDB state and direct invocations.
* **Market Hours Awareness:** Critical agents refuse to operate outside NYSE trading hours.
* **Failure Resilience:** Comprehensive retry logic and structured error logging.

---

## 2. Agent Architecture

### 2.1 Agent Profiles & Responsibilities

| Agent / Component | Type | Responsibility |
| --- | --- | --- |
| **Client Agent** | Future Phase | Human-facing interface; proxy for user commands. |
| **Portfolio Manager** | Orchestrator | Central router; maintains state in DuckDB; triggers Judge-Critic and executor, and responds to user/client |
| **Data Gatherer** | Python Script | Fetches historical data & subscribes to Alpaca WebSockets. Fetches fundamentals from AlphaVagent |
| **Quant Analyst** | Langchain `deepAgent` (GPT-4) | Calculates technical indicators; generates 30-min summaries, then end-of-day summary using these summaries, store to duckdb |
| **Backtester** | Langchain `deepagent` (GPT-4) | Runs post-market simulations; provides insights to Judge-Critic. |
| **Executor** | Langchain `deepagent` | Executes trades via Alpaca API; handles webhook callbacks. |
| **Judge-Critic** | Subsystem (2 Agents)  Langchain `deepagent` | Debate loop (Max 3 iterations) to finalize buy/sell/hold decisions. Traces and persists reasoning for decision |

---

## 3. Communication Architecture

### 3.1 Inter-Agent Communication Patterns

1. **Pattern 1: State-Based (Primary)**
* Data Gatherer writes to DuckDB with `processed=false`.
* Quant Analyst polls DuckDB every 30 minutes.

2. **Pattern 2: Direct Invocation**
* Portfolio Manager calls Quant/Backtester/Judge as Python class instances (Synchronous)

3. **Pattern 3: JSON-RPC + SSE**
* Used for client-facing interactions and streaming responses.

4. **Pattern 4: Webhooks**
* Executor sends callbacks for long-running trade executions.
* Any other long-running tasks between agents

4. **Pattern 5: A2A Wrapper**
* Future phase

---

## 4. Data Architecture

### 4.1 DuckDB Schema Design

* **Core Tables (Phase 1):** `watchlist`, `market_bars` (1-min OHLCV), `historical_trades` `fundamentals`, `dividend_history`, `earnings_history`, `income_history`.
* **Future Tables:** `portfolio`, `trades`, `backtest_results`, `agent_logs`, `reasoning_logic`.
* Subject to change as per API response

### 4.2 DAO Layer Pattern

* All agents access DuckDB through **DAOs** (Data Access Objects) to ensure no direct SQL is embedded in agent logic.
* Includes `MarketDataDAO`, `PortfolioDAO`, and `BacktestDAO`
* Others TBD

---

## 5. External Integrations

* **Alpaca API:** Used for historical data, live WebSocket streams, and trade execution.
* **Alpha Vantage API:** Used for weekly fundamental data (PE ratios, Graham metrics).
* **OpenAI API:** GPT-4 powers the reasoning agents (Quant, Judge, Critic, Portfolio Manager).

---

## 6. Skills & Tools Framework

All tools/skills follow LangChain `deepagents` SKILLS.md pattern. Functions are normal python functions, i.e. for Alpaca/Alpha Vantage and duckdb, based on ticker configured

* **Alpaca Functions:** Websocket, historical: `fetch_historical_bars`, `fetch_historical_trades`
* **Alpha Vantage Functions:** `overview`, `dividend`, `earnings`, `income_statement`.
* **Quant Metrics Skills:** `calculate_rsi`, `calculate_macd`, `calculate_margin_of_safety`.
* **DuckDB Functions:** `save_market_data`, `mark_processed`.

---

## 7. Operational Workflow

### 7.1 Daily Workflow (Market Day)

* **09:30 AM ET:** Market Open. Data Gatherer starts streaming to DuckDB.
* **10:00 AM ET:** First Quant Analysis. Runs every 30 mins thereafter.
* **Continuous Loop:** If volatility is detected, **Judge-Critic** debates. If approved, **Executor** trades.
* **04:00 PM ET:** Market Close. Data Gatherer shuts down; EOD report generated.
* **05:00 PM ET:** Post-Market. Backtester runs simulations on the day's data.

---

## 8. Configuration & Security

### 8.1 Environment Management

* **`.env`:** Stores sensitive keys (Alpaca, OpenAI). **Never committed to Git.**
* **`config.json`:** Stores non-sensitive settings (Watchlist (only contains AAPL), risk thresholds, intervals).

### 8.2 Risk Management

* **Position Limits:** Defined in `config.json`.
* **HITL (Human-in-the-Loop):** Gates for high-value trades or parameter changes.
* **Sandbox Mode:** Uses Alpaca Sandbox for all initial testing.

---

## 9. Phase 1 Scope & Deliverables

### Module Execution Order

1. **Foundation:** Directory structure, `.env.example`, requirements.txt - Scaffolding
2. **Core Utilities:** Logger, Config Loader, Market Hours decorator.
3. **Data Layer:** DuckDB schemas and Base DAO.
4. **Skills:** Alpaca API and Alpha Vantage md files.
5. **Data Gatherer:** Main script and Cron wrapper with main function
6. **Testing:** Unit and integration tests for all components above.

---

## 10. Future Phases

* **Phase 2:** Quant Analyst Agent.
* **Phase 3:** Portfolio Manager FastAPI Server.
* **Phase 4:** Judge-Critic Subsystem.
* **Phase 5:** Executor Agent (Webhooks).
* **Phase 6:** Backtester Engine.
* **Phase 7:** Client Conversational Agent.