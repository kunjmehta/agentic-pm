"""Centralized logging utility for the application.

This module provides a structured logging setup with:
- File and console handlers
- Configurable log levels
- Automatic log directory creation
- Agent-specific loggers
- Structured format with timestamps

Usage:
    from src.utils.logger import get_logger

    # Get logger for a module
    logger = get_logger(__name__)
    logger.info("Processing started")
    logger.error("An error occurred", exc_info=True)

    # Get agent-specific logger
    quant_logger = get_logger("quant_analyst")
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


class LoggerSetup:
    """Centralized logger setup with singleton pattern."""

    _initialized = False
    _loggers = {}

    @classmethod
    def setup(
        cls,
        log_dir: Path,
        log_level: str = "INFO",
        console_level: str = "INFO",
        file_level: str = "DEBUG"
    ) -> None:
        """Setup logging configuration.

        Args:
            log_dir: Directory to store log files
            log_level: Default log level for root logger
            console_level: Log level for console output
            file_level: Log level for file output
        """
        if cls._initialized:
            return

        # Create log directory if it doesn't exist
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create formatters
        detailed_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        console_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
            datefmt='%H:%M:%S'
        )

        # Setup root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))

        # Remove existing handlers
        root_logger.handlers.clear()

        # Console handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, console_level.upper()))
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

        # File handler - main application log
        today = datetime.now().strftime("%Y-%m-%d")
        main_log_file = log_dir / f"app_{today}.log"
        file_handler = logging.FileHandler(main_log_file, encoding='utf-8')
        file_handler.setLevel(getattr(logging, file_level.upper()))
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)

        # Error log file - errors and above only
        error_log_file = log_dir / f"errors_{today}.log"
        error_handler = logging.FileHandler(error_log_file, encoding='utf-8')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(error_handler)

        cls._initialized = True

        # Log initialization
        init_logger = logging.getLogger(__name__)
        init_logger.info(f"Logging initialized - Main log: {main_log_file}")
        init_logger.info(f"Error log: {error_log_file}")

    @classmethod
    def get_logger(cls, name: str, log_file: Optional[str] = None) -> logging.Logger:
        """Get or create a logger with the given name.

        Args:
            name: Logger name (typically __name__ or agent name)
            log_file: Optional separate log file for this logger

        Returns:
            logging.Logger: Configured logger instance
        """
        if not cls._initialized:
            # Auto-initialize with defaults if not already setup
            from src.utils.config_loader import config
            log_path = config.get("logging.path", default="logs")
            log_level = config.get("logging.level", default="INFO")

            project_root = Path(__file__).parent.parent.parent
            cls.setup(
                log_dir=project_root / log_path,
                log_level=log_level
            )

        # Return cached logger if exists
        if name in cls._loggers:
            return cls._loggers[name]

        # Create new logger
        logger = logging.getLogger(name)

        # Add separate file handler if specified
        if log_file:
            from src.utils.config_loader import config
            log_path = config.get("logging.path", default="logs")
            project_root = Path(__file__).parent.parent.parent
            log_dir = project_root / log_path

            file_path = log_dir / log_file
            handler = logging.FileHandler(file_path, encoding='utf-8')
            handler.setLevel(logging.DEBUG)

            formatter = logging.Formatter(
                fmt='%(asctime)s | %(levelname)-8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        cls._loggers[name] = logger
        return logger


# Convenience function
def get_logger(name: str, log_file: Optional[str] = None) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name (typically __name__ or agent name)
        log_file: Optional separate log file for this logger

    Returns:
        logging.Logger: Configured logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing started")
        >>> logger.error("Error occurred", exc_info=True)
    """
    return LoggerSetup.get_logger(name, log_file)


def setup_logging(
    log_dir: Optional[Path] = None,
    log_level: str = "INFO"
) -> None:
    """Manually setup logging configuration.

    Args:
        log_dir: Directory to store log files (default: from config)
        log_level: Log level (default: from config)
    """
    if log_dir is None:
        from src.utils.config_loader import config
        log_path = config.get("logging.path", default="logs")
        project_root = Path(__file__).parent.parent.parent
        log_dir = project_root / log_path

    LoggerSetup.setup(log_dir=log_dir, log_level=log_level)


if __name__ == "__main__":
    """Test the logger."""
    # Add project root to path for direct execution
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("Testing Logger...\n")

    # Setup logging
    setup_logging()

    # Create test loggers
    logger1 = get_logger(__name__)
    logger2 = get_logger("data_gatherer")
    logger3 = get_logger("quant_analyst")

    # Test different log levels
    logger1.debug("This is a debug message")
    logger1.info("This is an info message")
    logger1.warning("This is a warning message")
    logger1.error("This is an error message")

    # Test different modules
    logger2.info("Data gathering started for AAPL")
    logger3.info("Calculating RSI for AAPL")

    # Test exception logging
    try:
        raise ValueError("Test exception")
    except ValueError:
        logger1.error("Caught an exception", exc_info=True)

    print("\n✓ Logger test complete - Check logs/ directory for output")
