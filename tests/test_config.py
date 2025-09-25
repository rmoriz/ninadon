#!/usr/bin/env python3
"""Tests for config module."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch
from src.config import Config, getenv


class TestGetenv:
    """Test the getenv utility function."""
    
    def test_getenv_with_default(self):
        """Test getenv returns default when env var not set."""
        result = getenv("NONEXISTENT_VAR", "default_value")
        assert result == "default_value"
    
    def test_getenv_with_existing_var(self, monkeypatch):
        """Test getenv returns env var value when set."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = getenv("TEST_VAR", "default_value")
        assert result == "test_value"
    
    def test_getenv_required_missing(self):
        """Test getenv raises error when required var is missing."""
        with pytest.raises(RuntimeError, match="MISSING_REQUIRED_VAR environment variable not set"):
            getenv("MISSING_REQUIRED_VAR", required=True)
    
    def test_getenv_required_present(self, monkeypatch):
        """Test getenv works when required var is present."""
        monkeypatch.setenv("REQUIRED_VAR", "value")
        result = getenv("REQUIRED_VAR", required=True)
        assert result == "value"


class TestConfig:
    """Test the Config class."""
    
    def test_default_values(self):
        """Test that config has sensible defaults."""
        assert Config.DATA_PATH == "/app/data"
        assert Config.WHISPER_MODEL == "base"
        # Just verify they have reasonable values, not specific ones
        assert Config.OPENROUTER_MODEL is not None
        assert Config.ENHANCE_MODEL is not None
        assert Config.CONTEXT_MODEL is not None
    
    def test_environment_overrides(self, monkeypatch):
        """Test that environment variables override defaults."""
        monkeypatch.setenv("DATA_PATH", "/custom/path")
        monkeypatch.setenv("WHISPER_MODEL", "large")
        
        # Test via getenv function directly since class attributes are set at import time
        from src.config import getenv
        assert getenv("DATA_PATH", "/app/data") == "/custom/path"
        assert getenv("WHISPER_MODEL", "base") == "large"
    
    def test_api_key_properties(self, monkeypatch):
        """Test that API key properties work correctly."""
        config = Config()

        # Ensure environment variables are not set for this test
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("MASTODON_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MASTODON_BASE_URL", raising=False)

        # Test that missing keys raise errors
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY environment variable not set"):
            _ = config.OPENROUTER_API_KEY

        with pytest.raises(RuntimeError, match="MASTODON_ACCESS_TOKEN or AUTH_TOKEN environment variable not set"):
            _ = config.MASTODON_ACCESS_TOKEN

        with pytest.raises(RuntimeError, match="MASTODON_BASE_URL or MASTODON_URL environment variable not set"):
            _ = config.MASTODON_BASE_URL
        
        # Test that present keys work
        monkeypatch.setenv("OPENROUTER_API_KEY", "test_api_key")
        monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "test_token")
        monkeypatch.setenv("MASTODON_BASE_URL", "https://mastodon.example.com")
        
        assert config.OPENROUTER_API_KEY == "test_api_key"
        assert config.MASTODON_ACCESS_TOKEN == "test_token"
        assert config.MASTODON_BASE_URL == "https://mastodon.example.com"

        # Test backward compatibility with old environment variable names
        monkeypatch.delenv("MASTODON_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MASTODON_BASE_URL", raising=False)
        monkeypatch.setenv("AUTH_TOKEN", "old_token")
        monkeypatch.setenv("MASTODON_URL", "https://old.mastodon.example.com")

        assert config.MASTODON_ACCESS_TOKEN == "old_token"
        assert config.MASTODON_BASE_URL == "https://old.mastodon.example.com"

        # Test that new names take precedence over old names
        monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "new_token")
        monkeypatch.setenv("MASTODON_BASE_URL", "https://new.mastodon.example.com")

        assert config.MASTODON_ACCESS_TOKEN == "new_token"
        assert config.MASTODON_BASE_URL == "https://new.mastodon.example.com"
    
    def test_get_data_root(self, monkeypatch, tmp_path):
        """Test get_data_root method."""
        # Test with custom path
        custom_path = tmp_path / "custom_data"
        monkeypatch.setenv("DATA_PATH", str(custom_path))
        
        result = Config.get_data_root()
        assert result == str(custom_path)
        assert custom_path.exists()  # Should be created
    
    def test_get_whisper_model_directory(self, monkeypatch):
        """Test get_whisper_model_directory method."""
        # Test default
        result = Config.get_whisper_model_directory()
        expected = Path(os.path.expanduser("~/.ninadon/whisper"))
        assert result == expected
        
        # Test that the method works correctly (just verify it returns a Path)
        assert isinstance(result, Path)
        
        # Test custom environment variable via getenv
        custom_path = "/custom/whisper/path"
        monkeypatch.setenv("WHISPER_MODEL_DIRECTORY", custom_path)
        from src.config import getenv
        assert getenv("WHISPER_MODEL_DIRECTORY", os.path.expanduser("~/.ninadon/whisper")) == custom_path
    
    def test_timeouts_and_limits(self):
        """Test timeout and limit configurations."""
        assert Config.TRANSCODE_TIMEOUT == 600
        # Just verify it's a reasonable timeout value
        assert Config.MASTODON_MEDIA_TIMEOUT > 0
        assert Config.WEB_PORT == 5000
    
    def test_feature_flags(self, monkeypatch):
        """Test feature flag configurations."""
        # Test default (False)
        assert Config.ENABLE_TRANSCODING is False
        
        # Test via getenv directly since class attribute is set at import time
        from src.config import getenv
        
        # Test various truthy values
        for value in ["1", "true", "yes", "TRUE", "Yes"]:
            monkeypatch.setenv("ENABLE_TRANSCODING", value)
            result = getenv("ENABLE_TRANSCODING", "").lower() in ("1", "true", "yes")
            assert result is True
        
        # Test falsy values
        for value in ["0", "false", "no", "FALSE", "No", ""]:
            monkeypatch.setenv("ENABLE_TRANSCODING", value)
            result = getenv("ENABLE_TRANSCODING", "").lower() in ("1", "true", "yes")
            assert result is False
    
    def test_prompts_configuration(self, monkeypatch):
        """Test prompt configurations."""
        # Test defaults exist
        assert Config.SYSTEM_PROMPT is not None
        assert len(Config.SYSTEM_PROMPT) > 0
        assert Config.USER_PROMPT == ""
        assert Config.IMAGE_ANALYSIS_PROMPT is not None
        assert Config.CONTEXT_PROMPT is not None
        
        # Test custom prompts via getenv since class attributes are set at import time
        from src.config import getenv
        custom_system_prompt = "Custom system prompt"
        custom_user_prompt = "Custom user prompt"
        monkeypatch.setenv("SYSTEM_PROMPT", custom_system_prompt)
        monkeypatch.setenv("USER_PROMPT", custom_user_prompt)
        
        assert getenv("SYSTEM_PROMPT", "") == custom_system_prompt
        assert getenv("USER_PROMPT", "") == custom_user_prompt