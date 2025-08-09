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
                    ],
                    "title": "Test Video",
                    "description": "Test description #hashtag",
                    "uploader": "testuser"
                }
            else:
                return {
                    "requested_downloads": [{"filepath": str(tmp_path / "video.mp4")}],
                    "title": "Test Video",
                    "description": "Test description #hashtag",
                    "uploader": "testuser"
                }
        def prepare_filename(self, info): return str(tmp_path / "video.mp4")
    monkeypatch.setattr(main.yt_dlp, "YoutubeDL", FakeYDL)
    result = main.download_video("http://youtube.com/test", str(tmp_path))
    assert result[0].endswith("video.mp4")  # filepath
    assert result[1] == "Test Video"  # title
    assert result[2] == "Test description #hashtag"  # description
    assert result[3] == "testuser"  # uploader
    assert "#hashtag" in result[4]  # hashtags
    assert result[5] == "youtube"  # platform

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
    monkeypatch.setattr(main, "download_video", lambda url, tmpdir: (str(tmp_path / "video.mp4"), "title", "desc", "uploader", ["#test"], "youtube", "video/mp4"))
    monkeypatch.setattr(main, "transcribe_video", lambda path: "transcript")
    monkeypatch.setattr(main, "summarize_text", lambda t, d, u, i=None, c=None: "summary")
    monkeypatch.setattr(main, "maybe_reencode", lambda path, tmpdir: path)
    monkeypatch.setattr(main, "post_to_mastodon", lambda s, v, u, m: "http://mastodon/post")
    
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
    monkeypatch.setattr(main, "post_to_mastodon", lambda s, v, u, m: "http://mastodon/post")
    
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

def test_database_functionality(tmp_path, monkeypatch):
    # Test database and context functionality
    # Set DATA_PATH to tmp_path for testing
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    
    try:
        # Test adding to database
        main.add_to_database("testuser", "Test Title", "Test description #hashtag", ["#hashtag"], "youtube", "Test transcript", "Test image analysis")
        
        # Check if database file was created
        db_path = main.get_database_path("testuser")
        assert os.path.exists(db_path)
        
        # Load and verify database content
        database = main.load_database("testuser")
        assert len(database) == 1
        entry = database[0]
        assert entry["title"] == "Test Title"
        assert entry["description"] == "Test description #hashtag"
        assert entry["hashtags"] == ["#hashtag"]
        assert entry["platform"] == "youtube"
        assert entry["transcript"] == "Test transcript"
        assert entry["image_recognition"] == "Test image analysis"
        assert "date" in entry
        
        # Test context generation (mock the OpenRouter call)
        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": "Generated context summary"}}]}
        
        monkeypatch.setattr(main.requests, "post", lambda *a, **kw: FakeResp())
        os.environ["OPENROUTER_API_KEY"] = "dummy"
        
        context = main.generate_context_summary("testuser")
        assert context == "Generated context summary"
        
        # Check if context file was created
        context_path = main.get_context_path("testuser")
        assert os.path.exists(context_path)
        
        # Load and verify context
        loaded_context = main.load_context("testuser")
        assert loaded_context == "Generated context summary"
        
    except Exception as e:
        # Re-raise any exceptions for proper test failure reporting
        raise e

def test_data_path_configuration(tmp_path, monkeypatch):
    # Test that DATA_PATH environment variable works correctly
    custom_data_path = tmp_path / "custom_data"
    monkeypatch.setenv("DATA_PATH", str(custom_data_path))
    
    # Test get_data_root function
    data_root = main.get_data_root()
    assert data_root == str(custom_data_path)
    assert os.path.exists(custom_data_path)
    
    # Test that database and context paths use the custom data path
    db_path = main.get_database_path("testuser")
    context_path = main.get_context_path("testuser")
    
    expected_user_dir = custom_data_path / "testuser"
    assert db_path == str(expected_user_dir / "database.json")
    assert context_path == str(expected_user_dir / "context.json")
    assert os.path.exists(expected_user_dir)
    
    # Test with default DATA_PATH (when not set) - use a different temp path
    default_test_path = tmp_path / "default_test"
    monkeypatch.delenv("DATA_PATH", raising=False)
    monkeypatch.setenv("DATA_PATH", str(default_test_path))
    default_data_root = main.get_data_root()
    assert default_data_root == str(default_test_path)
    assert os.path.exists(default_test_path)

def test_context_generation_with_existing_context(tmp_path, monkeypatch):
    # Test that context generation includes existing context
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    
    # Create initial database entry
    main.add_to_database("testuser", "First Video", "Description", ["#test"], "youtube", "Transcript")
    
    # Create initial context
    context_data = {
        "generated_at": "2024-01-01T00:00:00",
        "summary": "Previous context about user's content patterns",
        "based_on_entries": 1
    }
    context_path = main.get_context_path("testuser")
    with open(context_path, 'w', encoding='utf-8') as f:
        import json
        json.dump(context_data, f)
    
    # Mock the OpenRouter call to capture the request
    captured_requests = []
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "Updated context summary"}}]}
    
    def mock_post(url, headers=None, json=None):
        captured_requests.append(json)
        return FakeResp()
    
    monkeypatch.setattr(main.requests, "post", mock_post)
    os.environ["OPENROUTER_API_KEY"] = "dummy"
    
    # Generate new context
    result = main.generate_context_summary("testuser")
    
    # Verify that the request included the existing context
    assert len(captured_requests) == 1
    request_data = captured_requests[0]
    user_content = request_data["messages"][1]["content"]
    
    # Check that existing context was included
    assert "Previous context summary:" in user_content
    assert "Previous context about user's content patterns" in user_content
    
    # Verify the result
    assert result == "Updated context summary"

def test_database_duplicate_handling(tmp_path, monkeypatch):
    # Test that duplicate videos update existing entries instead of creating new ones
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    
    # Add initial entry
    main.add_to_database("testuser", "Test Video", "Description", ["#test"], "youtube", "Original transcript")
    
    # Verify initial entry
    database = main.load_database("testuser")
    assert len(database) == 1
    assert database[0]["transcript"] == "Original transcript"
    assert "image_recognition" not in database[0]
    
    # Add same video again with updated content and image analysis
    main.add_to_database("testuser", "Test Video", "Updated description", ["#test", "#new"], "youtube", "Updated transcript", "Image analysis")
    
    # Verify that entry was updated, not duplicated
    database = main.load_database("testuser")
    assert len(database) == 1  # Still only one entry
    
    # Verify updated content
    entry = database[0]
    assert entry["title"] == "Test Video"
    assert entry["description"] == "Updated description"
    assert entry["hashtags"] == ["#test", "#new"]
    assert entry["transcript"] == "Updated transcript"
    assert entry["image_recognition"] == "Image analysis"
    
    # Add different video to ensure new entries still work
    main.add_to_database("testuser", "Different Video", "Different description", ["#different"], "tiktok", "Different transcript")
    
    # Verify we now have two entries
    database = main.load_database("testuser")
    assert len(database) == 2
    assert database[0]["title"] == "Test Video"  # Updated entry
    assert database[1]["title"] == "Different Video"  # New entry
    
    # Test same title but different platform (should be treated as different video)
    main.add_to_database("testuser", "Test Video", "Same title different platform", ["#instagram"], "instagram", "Instagram transcript")
    
    # Verify we now have three entries
    database = main.load_database("testuser")
    assert len(database) == 3
    
    # Verify all three entries exist
    titles_platforms = [(entry["title"], entry["platform"]) for entry in database]
    assert ("Test Video", "youtube") in titles_platforms
    assert ("Different Video", "tiktok") in titles_platforms
    assert ("Test Video", "instagram") in titles_platforms

def test_configurable_image_analysis_prompt(monkeypatch, tmp_path):
    # Test that IMAGE_ANALYSIS_PROMPT environment variable works
    custom_prompt = "Describe the visual elements and narrative flow in these video frames"
    monkeypatch.setenv("IMAGE_ANALYSIS_PROMPT", custom_prompt)
    
    # Mock the OpenRouter call to capture the request
    captured_requests = []
    class FakeResp:
        status_code = 200
        text = '{"choices": [{"message": {"content": "Custom analysis result"}}]}'
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "Custom analysis result"}}]}
    
    def mock_post(url, headers=None, json=None):
        captured_requests.append(json)
        return FakeResp()
    
    monkeypatch.setattr(main.requests, "post", mock_post)
    os.environ["OPENROUTER_API_KEY"] = "dummy"
    
    # Create temporary image files for testing
    temp_images = []
    try:
        for i in range(2):
            tmp_img = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            tmp_img.write(b"fake_image_data")
            tmp_img.close()
            temp_images.append(tmp_img.name)
        
        # Call the image analysis function
        result = main.analyze_images_with_openrouter(temp_images)
        
        # Verify that the custom prompt was used
        assert len(captured_requests) == 1
        request_data = captured_requests[0]
        messages = request_data["messages"]
        user_message = messages[0]
        content = user_message["content"]
        
        # Find the text content in the message
        text_content = None
        for item in content:
            if item["type"] == "text":
                text_content = item["text"]
                break
        
        assert text_content == custom_prompt
        assert result == "Custom analysis result"
        
    finally:
        # Clean up temporary files
        for img_path in temp_images:
            try:
                os.unlink(img_path)
            except:
                pass
