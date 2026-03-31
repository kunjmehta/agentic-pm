Objective: Develop the Backtester Agent for the "Agentic Portfolio Manager" system based on the provided System Design Document. This agent is a `deepagent` powered by GPT-4o-mini that runs post-market simulations.

Context & Constraints:

    Architecture: Use the LangChain `deepagent` pattern as for the other two agents. Follow similar structure to the other two agents, have tools for sensitive functions and SKILLS.md files for others as well as quantitative functions

    Data Layer: The agent must never write direct SQL. It must interact with the system via the BacktestDAO to pull from and push to DuckDB.

    Interaction: The agent will interact with the portfolio manager agent which will call it, save results in DB accessed by the PM agent to make decisions on trade

    Scope: For Phase 4, focus on a simulation engine that evaluates the "What If" scenarios provided by the Quant Analyst’s summaries.

Requirements for the Implementation:

    Skills (Tools) Implementation:

        Create Python functions for:

            run_daily_simulation(ticker, strategy_params): Simulates trades against the day's 1-min DuckDB data.

            calculate_performance_metrics(): Computes Sharpe Ratio, Maximum Drawdown, and Win Rate for the day's simulated session.

            fetch_eod_state(): Retrieves the closing state of the portfolio from PortfolioDAO.

    Agent Logic (The Prompting):

        Define the System Prompt in a AGENT.MD file for the Backtester. 

        The agent must output a JSON summary of insights to be used by the Judge-Critic subsystem in future iterations. For now, to be used by the portfolio manager agent

    Integration Points:

        Reference the MarketDataDAO for historical 1-min bars.

        Have access to portfolio data

        Invoked by the portfolio manager agent

    Existing implementation:

        Add new schema files in config/schema for the DB

        Add a new DAO class

        Existing middleware for logging and market check to be used
