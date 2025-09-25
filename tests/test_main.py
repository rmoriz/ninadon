import os
import sys
import tempfile
import pytest

import src.main as main

from unittest.mock import patch, MagicMock

@pytest.fixture
def fake_video_path(tmp_path):
    # Create a fake video file
    file = tmp_path / "video.mp4"
    file.write_bytes(b"0" * (5 * 1024 * 1024))  # 5 MB
    return str(file)

def test_maybe_reencode_small(fake_video_path):
    # Should not reencode if under 25MB
    result = main.maybe_reencode(fake_video_path, os.path.dirname(fake_video_path))
    assert result == fake_video_path

def test_maybe_reencode_large(tmp_path):
    # Should reencode if over 25MB
    file = tmp_path / "video.mp4"
    file.write_bytes(b"0" * (30 * 1024 * 1024))  # 30 MB
    with patch("subprocess.run") as mock_run:
        result = main.maybe_reencode(str(file), str(tmp_path))
        assert result == str(tmp_path / "video_h265.mp4")
        mock_run.assert_called_once()

def test_main_flow(monkeypatch, tmp_path):
    # Patch all major functions to simulate main() flow
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "title", "desc", "uploader", ["#test"], "youtube", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")
    monkeypatch.setattr(main, "summarize_text", lambda t, d, u, i=None, c=None: "summary")
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)
    monkeypatch.setattr(main, "post_to_mastodon", lambda s, v, u, m=None, d=None: "http://mastodon/post")

    # Mock database functions
    monkeypatch.setattr(main, "add_to_database", lambda *args: None)
    monkeypatch.setattr(main, "generate_context_summary", lambda uploader: "test context")

    # Simulate CLI args
    sys_argv = sys.argv
    sys.argv = ["main.py", "http://test"]
    try:
        main.main()
    finally:
        sys.argv = sys_argv

def test_main_flow_dry_run(monkeypatch, tmp_path):
    # Patch all major functions to simulate main() flow with dry run
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "title", "desc", "uploader", ["#test"], "youtube", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")
    monkeypatch.setattr(main, "summarize_text", lambda t, d, u, i=None, c=None: "summary")
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)

    # Mock database functions
    monkeypatch.setattr(main, "add_to_database", lambda *args: None)
    monkeypatch.setattr(main, "generate_context_summary", lambda uploader: "test context")

    # Mock post_to_mastodon to ensure it's NOT called during dry run
    post_to_mastodon_called = False
    def mock_post_to_mastodon(*args, **kwargs):
        nonlocal post_to_mastodon_called
        post_to_mastodon_called = True
        return "http://mastodon/post"

    monkeypatch.setattr(main, "post_to_mastodon", mock_post_to_mastodon)

    # Simulate CLI args with --dry flag
    sys_argv = sys.argv
    sys.argv = ["main.py", "--dry", "http://test"]
    try:
        main.main()
        # Verify that post_to_mastodon was NOT called
        assert not post_to_mastodon_called, "post_to_mastodon should not be called during dry run"
    finally:
        sys.argv = sys_argv

def test_enhance_functionality(monkeypatch, tmp_path):
    # Test the --enhance flag functionality
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "title", "desc", "uploader", ["#test"], "youtube", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")

    # Mock image extraction and analysis
    monkeypatch.setattr(main, "extract_still_images", lambda video_path, tmpdir: ["img1.jpg", "img2.jpg"])
    monkeypatch.setattr(main, "analyze_images_with_openrouter", lambda images: "image analysis result")

    # Mock database functions
    monkeypatch.setattr(main, "add_to_database", lambda *args: None)
    monkeypatch.setattr(main, "generate_context_summary", lambda uploader: "test context")

    # Track if summarize_text is called with image analysis and context
    summarize_calls = []
    def mock_summarize_text(transcript, description, uploader, image_analysis=None, context=None):
        summarize_calls.append((transcript, description, uploader, image_analysis, context))
        return "enhanced summary"

    monkeypatch.setattr(main, "summarize_text", mock_summarize_text)
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)
    monkeypatch.setattr(main, "post_to_mastodon", lambda s, v, u, m=None, d=None: "http://mastodon/post")

    # Simulate CLI args with --enhance flag
    sys_argv = sys.argv
    sys.argv = ["main.py", "--enhance", "http://test"]
    try:
        main.main()
        # Verify that summarize_text was called with image analysis and context
        assert len(summarize_calls) == 1
        transcript, description, uploader, image_analysis, context = summarize_calls[0]
        assert transcript == "transcript"
        assert description == "desc"
        assert uploader == "uploader"
        assert image_analysis == "image analysis result"
        assert context == "test context"
    finally:
        sys.argv = sys_argv

def test_enhance_with_dry_run(monkeypatch, tmp_path):
    # Test the --enhance flag with --dry run
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "title", "desc", "uploader", ["#test"], "youtube", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")

    # Mock image extraction and analysis
    monkeypatch.setattr(main, "extract_still_images", lambda video_path, tmpdir: ["img1.jpg", "img2.jpg"])
    monkeypatch.setattr(main, "analyze_images_with_openrouter", lambda images: "image analysis result")

    # Mock database functions
    monkeypatch.setattr(main, "add_to_database", lambda *args: None)
    monkeypatch.setattr(main, "generate_context_summary", lambda uploader: "test context")

    # Track if summarize_text is called with image analysis and context
    summarize_calls = []
    def mock_summarize_text(transcript, description, uploader, image_analysis=None, context=None):
        summarize_calls.append((transcript, description, uploader, image_analysis, context))
        return "enhanced summary"

    monkeypatch.setattr(main, "summarize_text", mock_summarize_text)
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)

    # Mock post_to_mastodon to ensure it's NOT called during dry run
    post_to_mastodon_called = False
    def mock_post_to_mastodon(*args, **kwargs):
        nonlocal post_to_mastodon_called
        post_to_mastodon_called = True
        return "http://mastodon/post"

    monkeypatch.setattr(main, "post_to_mastodon", mock_post_to_mastodon)

    # Simulate CLI args with both --dry and --enhance flags
    sys_argv = sys.argv
    sys.argv = ["main.py", "--dry", "--enhance", "http://test"]
    try:
        main.main()
        # Verify that summarize_text was called with image analysis and context
        assert len(summarize_calls) == 1
        transcript, description, uploader, image_analysis, context = summarize_calls[0]
        assert image_analysis == "image analysis result"
        assert context == "test context"
        # Verify that post_to_mastodon was NOT called
        assert not post_to_mastodon_called, "post_to_mastodon should not be called during dry run"
    finally:
        sys.argv = sys_argv

def test_download_whisper_model_requires_url_without_flag(monkeypatch, tmp_path):
    # Test that URL is required when not using --download-whisper-model
    sys_argv = sys.argv
    sys.argv = ["main.py"]  # No URL and no --download-whisper-model
    try:
        with pytest.raises(SystemExit):  # argparse calls sys.exit when required args are missing
            main.main()
    finally:
        sys.argv = sys_argv