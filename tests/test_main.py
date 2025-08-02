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
    monkeypatch.setattr(main, "summarize_text", lambda t, d, u: "summary")
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)
    monkeypatch.setattr(main, "post_to_mastodon", lambda s, v, u, m: "http://mastodon/post")
    # Simulate CLI args
    sys_argv = sys.argv
    sys.argv = ["main.py", "http://test"]
    try:
        main.main()
    finally:
        sys.argv = sys_argv
