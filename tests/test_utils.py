#!/usr/bin/env python3
"""Tests for utils module."""

import sys
from io import StringIO
from src.utils import print_flush


class TestPrintFlush:
    """Test the print_flush utility function."""
    
    def test_print_flush_basic(self, monkeypatch):
        """Test that print_flush prints and flushes."""
        # Capture stdout
        captured_output = StringIO()
        monkeypatch.setattr(sys, 'stdout', captured_output)
        
        # Mock flush method to track if it's called
        flush_called = []
        original_flush = captured_output.flush
        def mock_flush():
            flush_called.append(True)
            return original_flush()
        captured_output.flush = mock_flush
        
        print_flush("test message")
        
        # Check output and flush
        assert captured_output.getvalue() == "test message\n"
        assert len(flush_called) == 1
    
    def test_print_flush_multiple_args(self, monkeypatch):
        """Test print_flush with multiple arguments."""
        captured_output = StringIO()
        monkeypatch.setattr(sys, 'stdout', captured_output)
        
        print_flush("arg1", "arg2", "arg3")
        assert captured_output.getvalue() == "arg1 arg2 arg3\n"
    
    def test_print_flush_with_kwargs(self, monkeypatch):
        """Test print_flush with keyword arguments."""
        captured_output = StringIO()
        monkeypatch.setattr(sys, 'stdout', captured_output)
        
        print_flush("test", end="", sep="-")
        assert captured_output.getvalue() == "test"
        
        captured_output.truncate(0)
        captured_output.seek(0)
        
        print_flush("a", "b", "c", sep="|")
        assert captured_output.getvalue() == "a|b|c\n"
    
    def test_print_flush_empty(self, monkeypatch):
        """Test print_flush with no arguments."""
        captured_output = StringIO()
        monkeypatch.setattr(sys, 'stdout', captured_output)
        
        print_flush()
        assert captured_output.getvalue() == "\n"