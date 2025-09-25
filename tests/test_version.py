#!/usr/bin/env python3
"""Tests for version management."""

import re
from pathlib import Path

import pytest


class TestVersion:
    """Test version functionality."""

    def test_version_exists_in_init(self):
        """Test that version is defined in __init__.py."""
        from src import __version__

        assert __version__ is not None
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_version_format(self):
        """Test that version follows semantic versioning format."""
        from src import __version__

        # Test semantic versioning pattern (major.minor.patch)
        pattern = r"^\d+\.\d+\.\d+$"
        assert re.match(pattern, __version__), f"Version {__version__} doesn't match semantic versioning"

    def test_version_file_exists(self):
        """Test that VERSION file exists and matches __init__.py."""
        from src import __version__

        version_file = Path("VERSION")
        assert version_file.exists(), "VERSION file should exist"

        version_file_content = version_file.read_text().strip()
        assert version_file_content == __version__, "VERSION file should match __version__"

    def test_package_metadata(self):
        """Test that package metadata is defined."""
        from src import __author__, __description__, __version__

        assert __author__ is not None
        assert __description__ is not None
        assert __version__ is not None

        assert isinstance(__author__, str)
        assert isinstance(__description__, str)
        assert isinstance(__version__, str)

        assert len(__author__) > 0
        assert len(__description__) > 0
        assert len(__version__) > 0

    def test_version_is_current_major_version(self):
        """Test that version is in the 0.x.x range (pre-1.0 development)."""
        from src import __version__

        major_version = int(__version__.split(".")[0])
        minor_version = int(__version__.split(".")[1])
        # Should be 0.2.x or higher (refactored architecture)
        assert major_version == 0 and minor_version >= 2, "Should be version 0.2.x or higher (refactored architecture)"