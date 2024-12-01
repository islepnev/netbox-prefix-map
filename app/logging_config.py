"""
app/logging_config.py

Module for configuring logging in Linux-only environments.

This module sets up logging with both console and SysLog handlers.
"""

import logging
from logging.handlers import SysLogHandler
import sys


def setup_logging():
    """Configure logging for the script."""
    logger = logging.getLogger(__name__)
    # logger.setLevel(logging.DEBUG)

    # Console handler for INFO level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(levelname)-8s: %(message)s')  # Fixed width for severity
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # SysLog handler for INFO level
    try:
        syslog_handler = SysLogHandler(address='/dev/log')
        syslog_handler.setLevel(logging.INFO)
        syslog_formatter = logging.Formatter('%(levelname)s - %(message)s')
        syslog_handler.setFormatter(syslog_formatter)
        logger.addHandler(syslog_handler)
    except Exception as e:
        logger.error(f"Failed to set up SysLogHandler: {e}")
