"""Example client for testing SSE streaming endpoint.

This demonstrates how to consume Server-Sent Events from the Portfolio Manager API.
"""

import requests
import json
import sys


def stream_query(query: str, thread_id: str = "example-session", base_url: str = "http://localhost:8000"):
    """Stream a query to the Portfolio Manager and print responses in real-time.

    Args:
        query: Natural language query
        thread_id: Thread ID for conversation context
        base_url: API base URL
    """
    url = f"{base_url}/query"
    payload = {
        "query": query,
        "thread_id": thread_id,
        "apply_middleware": True
    }

    print(f"Streaming query: {query}")
    print("=" * 70)
    print()

    try:
        # Make streaming request
        response = requests.post(
            url,
            json=payload,
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=120
        )

        response.raise_for_status()

        # Process SSE events
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')

                # SSE format: "data: {...}"
                if line.startswith('data: '):
                    data_str = line[6:]  # Remove "data: " prefix
                    try:
                        event = json.loads(data_str)
                        event_type = event.get("type")

                        if event_type == "start":
                            print(f"[START] Query: {event.get('query')}")
                            print(f"Thread: {event.get('thread_id')}")
                            print()

                        elif event_type == "token":
                            # Print content as it arrives
                            content = event.get("content", "")
                            print(content, end="", flush=True)

                        elif event_type == "tool_start":
                            tool_name = event.get("tool", "unknown")
                            print(f"\n\n[TOOL] Calling: {tool_name}...", end="", flush=True)

                        elif event_type == "tool_end":
                            tool_name = event.get("tool", "unknown")
                            print(f" ✓", flush=True)

                        elif event_type == "done":
                            exec_time = event.get("execution_time_ms", 0)
                            print(f"\n\n[DONE] Completed in {exec_time}ms")
                            print("=" * 70)

                        elif event_type == "error":
                            error_msg = event.get("error", "Unknown error")
                            blocked_by = event.get("blocked_by", "")
                            print(f"\n\n[ERROR] {error_msg}")
                            if blocked_by:
                                print(f"Blocked by: {blocked_by}")
                            print("=" * 70)
                            return

                    except json.JSONDecodeError:
                        print(f"[WARNING] Could not parse event: {data_str}")

    except requests.exceptions.RequestException as e:
        print(f"\n[ERROR] Request failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stream queries to Portfolio Manager")
    parser.add_argument("query", nargs="?", default="What's my portfolio status?",
                        help="Query to send")
    parser.add_argument("--thread", default="example-session",
                        help="Thread ID for conversation context")
    parser.add_argument("--url", default="http://localhost:8000",
                        help="API base URL")

    args = parser.parse_args()

    print("Portfolio Manager - Streaming Client")
    print()

    # Example queries
    if args.query == "demo":
        queries = [
            "What's my portfolio status?",
            "Is my portfolio healthy?",
            "Should I buy AAPL? Run technical analysis."
        ]

        for i, query in enumerate(queries, 1):
            print(f"\n{'='*70}")
            print(f"Query {i}/{len(queries)}")
            print(f"{'='*70}\n")
            stream_query(query, thread_id=f"demo-{i}", base_url=args.url)
            print("\n")
    else:
        stream_query(args.query, thread_id=args.thread, base_url=args.url)
