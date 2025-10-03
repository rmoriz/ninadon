#!/usr/bin/env python3
"""Configuration management for Ninadon."""

import os
from pathlib import Path


def getenv(key, default=None, required=False):
    """Get environment variable with optional default and required validation."""
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"{key} environment variable not set")
    return val


class Config:
    """Application configuration."""

    # Paths
    DATA_PATH = getenv("DATA_PATH", "/app/data")
    WHISPER_MODEL_DIRECTORY = getenv(
        "WHISPER_MODEL_DIRECTORY", os.path.expanduser("~/.ninadon/whisper")
    )

    # Models
    WHISPER_MODEL = getenv("WHISPER_MODEL", "base")
    OPENROUTER_MODEL = getenv("OPENROUTER_MODEL", "tngtech/deepseek-r1t2-chimera:free")
    ENHANCE_MODEL = getenv("ENHANCE_MODEL", "google/gemini-2.5-flash-lite")
    CONTEXT_MODEL = getenv("CONTEXT_MODEL", "tngtech/deepseek-r1t2-chimera:free")

    # API Keys (loaded lazily to avoid import-time failures)
    @property
    def OPENROUTER_API_KEY(self):
        return getenv("OPENROUTER_API_KEY", required=True)

    @property
    def MASTODON_ACCESS_TOKEN(self):
        # Support both new and old environment variable names for backward compatibility
        token = getenv("MASTODON_ACCESS_TOKEN") or getenv("AUTH_TOKEN")
        if not token:
            raise RuntimeError(
                "MASTODON_ACCESS_TOKEN or AUTH_TOKEN environment variable not set"
            )
        return token

    @property
    def MASTODON_BASE_URL(self):
        # Support both new and old environment variable names for backward compatibility
        url = getenv("MASTODON_BASE_URL") or getenv("MASTODON_URL")
        if not url:
            raise RuntimeError(
                "MASTODON_BASE_URL or MASTODON_URL environment variable not set"
            )
        return url

    # Prompts
    SYSTEM_PROMPT = getenv(
        "SYSTEM_PROMPT",
        "Summarize the following video transcript, description, and account name. "
        "Additionally, create a detailed video description for visually impaired people "
        "(up to 1400 characters) that describes what happens in the video based on the "
        "transcript and any available visual information. Respond with valid JSON in this "
        'exact format: {"summary": "your summary here", "video_description": '
        '"detailed description for visually impaired up to 1400 characters"}',
    )
    USER_PROMPT = getenv("USER_PROMPT", "")
    IMAGE_ANALYSIS_PROMPT = getenv(
        "IMAGE_ANALYSIS_PROMPT",
        "Analyze these photos from a tiktok clip, make a connection between the photos",
    )
    CONTEXT_PROMPT = getenv(
        "CONTEXT_PROMPT",
        "Analyze the following video history and create a concise context summary that "
        "captures the user's content themes, interests, and patterns. Focus on recurring "
        "topics, style, and audience. If a previous context summary is provided, build "
        "upon it and update it with new insights from the recent videos, maintaining "
        "continuity while incorporating new patterns or changes.",
    )

    # Timeouts and limits
    TRANSCODE_TIMEOUT = int(getenv("TRANSCODE_TIMEOUT", "600"))
    MASTODON_MEDIA_TIMEOUT = int(getenv("MASTODON_MEDIA_TIMEOUT", "600"))

    # Features
    ENABLE_TRANSCODING = getenv("ENABLE_TRANSCODING", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # Web interface
    @property
    def WEB_USER(self):
        return getenv("WEB_USER")

    @property
    def WEB_PASSWORD(self):
        return getenv("WEB_PASSWORD")

    WEB_PORT = int(getenv("WEB_PORT", "5000"))

    INSTANCE_BLACKLIST = {
        "mastodon.social": "toxic moderation",
    }

    @classmethod
    def get_data_root(cls):
        """Get the root data directory, creating it if it doesn't exist."""
        # Refresh DATA_PATH in case environment changed
        data_path = getenv("DATA_PATH", "/app/data")
        os.makedirs(data_path, exist_ok=True)
        return data_path

    @classmethod
    def get_whisper_model_directory(cls):
        """Get the Whisper model directory as a Path object."""
        return Path(cls.WHISPER_MODEL_DIRECTORY)
