"""
app/logging_config.py

Module for configuring logging in Linux-only environments.

This module sets up logging with console, SysLog (when available) and an
in-memory buffer of recent warnings/errors shown on the /errors page.
"""

import collections
import logging
from logging.handlers import SysLogHandler
import os
import sys


class RecentLogHandler(logging.Handler):
    """Keeps the most recent formatted log records in memory."""

    def __init__(self, capacity=500, level=logging.WARNING):
        super().__init__(level)
        self.records = collections.deque(maxlen=capacity)

    def emit(self, record):
        try:
            self.records.append(self.format(record))
        except Exception:
            self.handleError(record)

    def lines(self):
        return list(self.records)


recent_log_handler = RecentLogHandler()
recent_log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(message)s'))

_configured = False


def setup_logging(level=logging.INFO, debug=False):
    """Configure logging for the script. Safe to call more than once."""
    global _configured
    if debug:
        level = logging.DEBUG
    logger = logging.getLogger()
    logger.setLevel(level)
    if _configured:
        return
    _configured = True

    # Console handler for INFO level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')  # Fixed width for severity
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Recent warnings and errors for the /errors page
    logger.addHandler(recent_log_handler)

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
