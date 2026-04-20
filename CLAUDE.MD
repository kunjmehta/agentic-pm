📋 Project Configuration - Python AI Developer Template
🚨 CRITICAL RULES

    One Module at a Time: Never modify multiple modules in a single turn. Focus, complete, and verify one module before moving to the next.

    Plan First: Before writing any code, generate a detailed execution plan and wait for user acknowledgment.

    Functional Entry Points: Every significant Python file must contain a if __name__ == "__main__": block for immediate functional testing.

    Environment Constraint: All code must be run with the local Conda environment which is given

    Strict Iteration: Follow the cycle: Plan → Code → Test → Review → Iterate until all tests pass before going back to the user to approve a commit.

🎯 PROJECT CONTEXT

    Project Type: Single-developer AI-driven Python application. This is a prototype autonomous multi-agent zero person portfolio manager

    Goals: Rapid prototyping with production-grade code quality and modularity.

    Tech Stack: Python 3.13+, Conda, Pytest, and Domain-Specific Libraries listed below

    Architecture: Modular monolith leaning toward micro-services; agentic best practice folder structure and separation of concerns; high emphasis on decoupled logic and fast inter-agent communication


🔧 DEVELOPMENT PATTERNS

    Coding Standards: Adhere strictly to PEP 8. Use Type Hinting for all function signatures. Implement SOLID design priciples, dependency injection and IoC where possible. Always think about edge cases and iterate over best low level design. Build the application for scale of at least in the order of thousands

    Docstrings: Use Google-style docstrings for all classes and functions.

    File Organization: * src/: Application logic.

        tests/: Parallel structure to src/.

        docs/: Any markdown files related to the project or other documentation

        New code should not add to bloat or complicate the existing codebase. Review how to integrate new code without creating bloat and refactor __main__ blocks and tests as per new code

    Testing Strategy: Unit tests via pytest. Functional verification via the main block in the working file.

    ## Async Python Patterns
    
    - All code that includes ETL, function calls / RPCs or tasks has to be written in async pattern by default
    
    - When writing async code, always ensure: coroutines are awaited, signal handlers are registered on the main thread only, and event loop cleanup is handled gracefully with `asyncio.run()` or equivalent.


🧠 MEMORY MANAGEMENT

    Context Storage: Use a .context.md file to store long-term architectural decisions and state.

    Decision Tracking: Document "Why" a specific library or pattern was chosen to prevent recursive re-explaining.

    Knowledge Persistence: Summarize progress at the end of each session to maintain a "warm start" for the next.


🚀 DEPLOYMENT & CI/CD

    Git Workflow:
        Check if git is initialized. If not, do it.

        Feature Branches: All work starts on feature/feature-name or fix/issue-name.

        Auto-Commits: Commit locally after every successful file iteration with a descriptive message provided user approves: git commit -m "feat: add validation logic to user_service.py".

        PR Creation: Once the feature is complete and all tests pass, generate a PR description and request a merge to main.

    Conda: Export environment changes to environment.yml and requirements.txt immediately after adding new dependencies.

📊 MONITORING & ANALYTICS

    Logging: Use the standard logging library. Avoid print() statements in production code, unless asked explicitly by the user

    Performance: Profile long-running loops using timeit or cProfile during the "Review" phase, if asked for by the user


🔒 SECURITY & COMPLIANCE

    Secret Management: Never hardcode keys. Use secret.json files

    Dependency Audits: Periodically run conda audit or equivalent to check for vulnerabilities.


🛠 WORKFLOW EXECUTION LOOP

For every task, the AI must follow these steps, and use available documentaion MCP servers where available:

    Generate Plan: Describe the file to be changed, the logic to be implemented, and the test cases.

    Conda Check: Verify agent is running in the conda environment provided by user

    Code Implementation: Write the code with a main function for testing. Ensure no addition in bloat and that all tests and code are sync

    Local Test: Run python <file_name>.py and pytest.

    Review & Iterate: If tests fail or the user requests changes, stay on the current file.

    Auto-Commit: Once approved, commit the single file.

    Push/PR: Once the feature branch is complete, push to origin and prepare the Pull Request.


DO NOT MAKE ANY MISTAKES

TECH STACK - Python 3.13+, Langchain 1.x, Deepagents, Langgraph, A2A-Python, duckdb
