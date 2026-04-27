"""Utility for loading LLM system prompts from the configured prompts directory.

Prompts are stored as plain Markdown files under ``config.prompts.dir``
(relative to the project root).  This keeps prompts editable without touching
Python source and allows operators to customise agent behaviour via config.

Usage::

    from src.common.utils import load_prompt

    _SYSTEM_PROMPT = load_prompt("portfolio_pm")
    # Loads src/server/prompts/portfolio_pm.md and returns the content as str.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils.logger import get_logger
from src.common.utils.config_loader import config

logger = get_logger(__name__)

# Resolve the prompts directory once at import time.
_PROMPTS_DIR: Path = project_root / config.get("prompts.dir", "src/server/prompts")


def load_prompt(name: str) -> str:
    """Load a system prompt from the configured prompts directory.

    Reads ``<prompts_dir>/<name>.md`` and returns its content as a string.

    Args:
        name: Prompt file stem (without ``.md`` extension), e.g. ``"portfolio_pm"``.

    Returns:
        Full prompt text as a string.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    prompt_path = _PROMPTS_DIR / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {prompt_path}. "
            f"Add '{name}.md' to '{_PROMPTS_DIR}' or update config.prompts.dir."
        )
    text = prompt_path.read_text(encoding="utf-8").strip()
    logger.debug("[prompt_loader] loaded %s (%d chars)", name, len(text))
    return text


if __name__ == "__main__":
    """Smoke test: list all available prompt files."""
    prompts = sorted(_PROMPTS_DIR.glob("*.md"))
    if not prompts:
        print(f"No prompt files found in {_PROMPTS_DIR}")
    else:
        print(f"Available prompts in {_PROMPTS_DIR}:")
        for p in prompts:
            content = p.read_text(encoding="utf-8")
            print(f"  {p.stem:30s}  ({len(content)} chars)")
