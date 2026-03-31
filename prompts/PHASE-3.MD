Prompt for Claude: Phase 3 Implementation

Context: You are developing the "Portfolio Manager Agent" (The Orchestrator) for an autonomous multi-agent trading system.
Current State: Phase 1 (Data/Infrastructure) and Phase 2 (Quant Analyst Agent) are complete.
Objective: Build the Portfolio Manager Agent using deepagents, unify the middleware, and establish the agent-to-agent (A2A) communication loop.

1. Architectural Requirements

Please implement the following components following the deepagents and LangChain patterns established in previous phases:
A. The Portfolio Manager Agent (Orchestrator)

    Primary Role: The central entry point for all user interactions.

    Tools: 
    
    - Alpaca Portfolio Tool: A tool to fetch real-time account equity, buying power, and open positions. Make hierarchical tools or skills if required. URLs for this: https://docs.alpaca.markets/docs/working-with-account, https://docs.alpaca.markets/docs/working-with-assets,  https://docs.alpaca.markets/docs/working-with-orders, https://docs.alpaca.markets/docs/working-with-positions. 
    
    Check all reference pages for trading API: https://docs.alpaca.markets/reference/assets-1


    - Quant Analyst Link: Integration to trigger the Quant Analyst Agent (from Phase 2) either as a tool or a direct invocation.

    - Observability Tool: A tool to log user queries, the sequence of tool calls, and final responses into a new DuckDB table.

    - State Management: Use thread_id to maintain conversation context and manage state across agent handoffs.

B. Data Layer Expansion (DuckDB)

Update the schema and DAOs to include:

    portfolio_snapshots: Stores EOD snapshots (equity, P/L, buying power).

    For portfolio_snapshots, add other tables related to portfolio depending on trading API.

    agent_interactions: An observability table storing timestamp, thread_id, user_query, tool_sequence (JSON), and response.

    parameters / configuration: This table to record current and historical account parameters with regards to risk and limits, that currently reside in config.json

C. Unified Middleware (Core Refactor)

Move existing Phase 2 middleware (MarketHoursGuard, Tracing, Prettifier) into a centralized /core/middleware/ directory. Ensure these are reusable by both the Quant Analyst and the Portfolio Manager.

2. Skills & Tools Framework (SKILLS.md)

Create a new portfolio_management.md skill file that enables the agent to:

    Analyze Portfolio Health: Compare current positions against risk thresholds in config.json.

    Query History: Retrieve past performance from the portfolio_snapshots table.

    Delegate to Quant: Recognize when a user asks about "Alpha" or "Technical Analysis" and route the sub-task to the Quant Analyst.

3. Technical Specifications

    Framework: deepagents (using create_deep_agent).

    Communication: Replace the Phase 2 FastAPI stub with a robust FastAPI entry point that calls the Portfolio Manager Agent.

    Agent Handoff: Implement logic where the Portfolio Manager passes the current thread_id to the Quant Analyst to ensure the "brain" state is consistent.

    Formatting: Use the Rich library or Markdown tables for all CLI/API outputs to ensure "White-Box" readability.

4. Deliverables

    Updated Schema: schema.sql (or Python equivalent) with the new tables.

    DAO Layer

    Agent Logic: PortfolioManagerAgent.py utilizing the SKILLS.md pattern.

    Middleware Refactor: Move logic to /core and update imports in the Quant Agent.

    FastAPI Entry Point: main.py serving as the user interface proxy.

5. Reference Code Structure

Ensure the Agent initialization looks similar to this:
Python

from deepagents import create_deep_agent
from core.middleware import MarketHoursGuard, InteractionLogger

portfolio_agent = create_deep_agent(
    tools=[fetch_alpaca_account, trigger_quant_analysis, log_to_db],
    system_prompt="You are the Lead Portfolio Manager. You coordinate with the Quant Analyst to manage the user's AAPL-centric portfolio.",
    # Apply unified middleware here
)

Code one module at a time, with a main function for functional testing and unit tests, before asking for approval and moving to next task. Finally, commit and push