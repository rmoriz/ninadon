import os
import sys
import types
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

def test_summarize_text(monkeypatch):
    # Mock requests.post to return a fake summary
    class FakeResp:
        status_code = 200
        text = '{"choices": [{"message": {"content": "summary"}}]}'
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "summary"}}]}
    monkeypatch.setattr(main.requests, "post", lambda *a, **kw: FakeResp())
    os.environ["OPENROUTER_API_KEY"] = "dummy"
    result = main.summarize_text("transcript", "desc", "uploader")
    assert result == "summary"

def test_transcribe_video(monkeypatch, fake_video_path):
    # Mock whisper.load_model and model.transcribe
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {"text": "transcribed"}
    monkeypatch.setattr(main.whisper, "load_model", lambda _: fake_model)
    result = main.transcribe_video(fake_video_path)
    assert result == "transcribed"

def test_download_video_selects_format(monkeypatch, tmp_path):
    # Mock yt_dlp.YoutubeDL to simulate info extraction and download
    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            if not download:
                return {
                    "formats": [
                        {"url": "http://a", "filesize": 10*1024*1024, "vcodec": "avc1", "acodec": "mp4a", "format_id": "1"},
                        {"url": "http://b", "filesize": 80*1024*1024, "vcodec": "avc1", "acodec": "mp4a", "format_id": "2"},
                    ]
                }
            else:
                return {"requested_downloads": [{"filepath": str(tmp_path / "video.mp4")}]}
        def prepare_filename(self, info): return str(tmp_path / "video.mp4")
    monkeypatch.setattr(main.yt_dlp, "YoutubeDL", FakeYDL)
    result = main.download_video("http://test", str(tmp_path))
    assert result[0].endswith("video.mp4")

def test_post_to_mastodon(monkeypatch, fake_video_path):
    # Mock Mastodon and its methods
    class FakeMastodon:
        def __init__(self, **kwargs): pass
        def media_post(self, path, mime_type): return {"id": "mediaid"}
        def media(self, media_id): return {"id": "mediaid", "url": "http://media", "processing": False}
        def status_post(self, text, media_ids): return {"url": "http://mastodon/post"}
    monkeypatch.setattr(main, "Mastodon", FakeMastodon)
    os.environ["AUTH_TOKEN"] = "dummy"
    os.environ["MASTODON_URL"] = "https://mastodon.social"
    url = main.post_to_mastodon("summary", fake_video_path, "http://source")
    assert url == "http://mastodon/post"

def test_main_flow(monkeypatch, tmp_path):
    # Patch all major functions to simulate main() flow
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "desc", "uploader", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")
    monkeypatch.setattr(main, "summarize_text", lambda t, d, u, i=None: "summary")
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)
    monkeypatch.setattr(main, "post_to_mastodon", lambda s, v, u, m: "http://mastodon/post")
    # Simulate CLI args
    sys_argv = sys.argv
    sys.argv = ["main.py", "http://test"]
    try:
        main.main()
    finally:
        sys.argv = sys_argv

def test_main_flow_dry_run(monkeypatch, tmp_path):
    # Patch all major functions to simulate main() flow with dry run
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "desc", "uploader", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")
    monkeypatch.setattr(main, "summarize_text", lambda t, d, u, i=None: "summary")
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)
    
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
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "desc", "uploader", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")
    
    # Mock image extraction and analysis
    monkeypatch.setattr(main, "extract_still_images", lambda video_path, tmpdir: ["img1.jpg", "img2.jpg"])
    monkeypatch.setattr(main, "analyze_images_with_openrouter", lambda images: "image analysis result")
    
    # Track if summarize_text is called with image analysis
    summarize_calls = []
    def mock_summarize_text(transcript, description, uploader, image_analysis=None):
        summarize_calls.append((transcript, description, uploader, image_analysis))
        return "enhanced summary"
    
    monkeypatch.setattr(main, "summarize_text", mock_summarize_text)
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)
    monkeypatch.setattr(main, "post_to_mastodon", lambda s, v, u, m: "http://mastodon/post")
    
    # Simulate CLI args with --enhance flag
    sys_argv = sys.argv
    sys.argv = ["main.py", "--enhance", "http://test"]
    try:
        main.main()
        # Verify that summarize_text was called with image analysis
        assert len(summarize_calls) == 1
        transcript, description, uploader, image_analysis = summarize_calls[0]
        assert transcript == "transcript"
        assert description == "desc"
        assert uploader == "uploader"
        assert image_analysis == "image analysis result"
    finally:
        sys.argv = sys_argv

def test_enhance_with_dry_run(monkeypatch, tmp_path):
    # Test the --enhance flag with --dry run
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "desc", "uploader", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")
    
    # Mock image extraction and analysis
    monkeypatch.setattr(main, "extract_still_images", lambda video_path, tmpdir: ["img1.jpg", "img2.jpg"])
    monkeypatch.setattr(main, "analyze_images_with_openrouter", lambda images: "image analysis result")
    
    # Track if summarize_text is called with image analysis
    summarize_calls = []
    def mock_summarize_text(transcript, description, uploader, image_analysis=None):
        summarize_calls.append((transcript, description, uploader, image_analysis))
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
        # Verify that summarize_text was called with image analysis
        assert len(summarize_calls) == 1
        transcript, description, uploader, image_analysis = summarize_calls[0]
        assert image_analysis == "image analysis result"
        # Verify that post_to_mastodon was NOT called
        assert not post_to_mastodon_called, "post_to_mastodon should not be called during dry run"
    finally:
        sys.argv = sys_argv
