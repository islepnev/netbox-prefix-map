"""
app/logging_config.py

Module for configuring logging in Linux-only environments.

This module sets up logging with both console and SysLog handlers.
"""

import logging
from logging.handlers import SysLogHandler
import os
import sys


def setup_logging(level=logging.INFO, debug=False):
    """Configure logging for the script."""
    if debug:
        level = logging.DEBUG
    logger = logging.getLogger()
    logger.setLevel(level)

    # Console handler for INFO level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter('%(levelname)-8s: %(message)s')  # Fixed width for severity
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # SysLog handler for INFO level
    try:
        DEV_LOG = '/dev/log'
        if os.path.exists(DEV_LOG):
            syslog_handler = SysLogHandler(address=DEV_LOG)
            syslog_handler.setLevel(level)
            syslog_formatter = logging.Formatter('%(levelname)s - %(message)s')
            syslog_handler.setFormatter(syslog_formatter)
            logger.addHandler(syslog_handler)
    except Exception as e:
        logger.error(f"Failed to set up SysLogHandler: {e}")
