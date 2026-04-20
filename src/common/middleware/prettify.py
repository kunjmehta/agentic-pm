"""Output prettification middleware.

Formats raw JSON tool outputs into Markdown using the Rich library
after agent execution completes.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
from typing import Any, Optional

from src.common.utils import get_logger

logger = get_logger(__name__)


class PrettifyMiddleware:
    """Middleware to format raw JSON tool outputs into Markdown.

    Uses after_agent hook to prettify final output with Rich library.
    """

    def after_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Prettify agent output after execution.

        Args:
            state: Final agent state.
            runtime: Agent runtime context.

        Returns:
            None to continue with original state.
        """
        structured_response = state.get("structured_response")
        if not structured_response:
            return None

        try:
            from rich import print as rprint
            from rich.json import JSON
            from rich.panel import Panel

            output_dict = (
                structured_response.model_dump()
                if hasattr(structured_response, "model_dump")
                else structured_response
            )
            json_str = json.dumps(output_dict, indent=2, default=str)
            rprint(Panel(
                JSON(json_str),
                title="[bold blue]Agent Output[/bold blue]",
                border_style="blue",
            ))
        except ImportError:
            logger.debug("Rich library not available, skipping prettification")

        return None


if __name__ == "__main__":
    print("=" * 60)
    print("PrettifyMiddleware Smoke Test")
    print("=" * 60)

    prettifier = PrettifyMiddleware()

    result = prettifier.after_agent({"structured_response": {"status": "ok"}}, None)
    assert result is None
    print("[OK] after_agent with structured_response returns None")

    result = prettifier.after_agent({}, None)
    assert result is None
    print("[OK] after_agent with no response returns None")

    print("\n[ALL OK] PrettifyMiddleware smoke test complete")
