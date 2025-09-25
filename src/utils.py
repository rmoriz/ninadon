#!/usr/bin/env python3
"""Utility functions for Ninadon."""

import sys


def print_flush(*args, **kwargs):
    """Print with automatic flush to ensure immediate output."""
    import builtins

    builtins.print(*args, **kwargs)
    sys.stdout.flush()
