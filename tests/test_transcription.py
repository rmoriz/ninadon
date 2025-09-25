#!/usr/bin/env python3
"""Tests for transcription module."""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from src.transcription import (
    get_whisper_model_directory, download_whisper_model, get_whisper_model,
    transcribe_video, parse_subtitle_file, extract_transcript_from_platform
)


class TestGetWhisperModelDirectory:
    """Test Whisper model directory functionality."""
    
    def test_get_whisper_model_directory_default(self):
        """Test default whisper model directory."""
        with patch('src.transcription.Config') as mock_config:
            mock_config.get_whisper_model_directory.return_value = Path("~/.ninadon/whisper").expanduser()
            
            result = get_whisper_model_directory()
            assert isinstance(result, Path)
            mock_config.get_whisper_model_directory.assert_called_once()
    
    def test_get_whisper_model_directory_custom(self, monkeypatch):
        """Test custom whisper model directory."""
        custom_path = "/custom/whisper/path"
        with patch('src.transcription.Config') as mock_config:
            mock_config.get_whisper_model_directory.return_value = Path(custom_path)
            
            result = get_whisper_model_directory()
            assert result == Path(custom_path)


class TestDownloadWhisperModel:
    """Test Whisper model downloading functionality."""
    
    def test_download_whisper_model_success(self, tmp_path):
        """Test successful model download."""
        model_dir = tmp_path / "whisper"
        fake_model = MagicMock()
        
        with patch('src.transcription.get_whisper_model_directory', return_value=model_dir), \
             patch('src.transcription.whisper.load_model', return_value=fake_model) as mock_load, \
             patch('src.transcription.print_flush'):
            
            result = download_whisper_model("base")
            
            assert result == fake_model
            assert model_dir.exists()
            assert (model_dir / ".cache").exists()
            mock_load.assert_called_once_with("base", download_root=str(model_dir))
    
    def test_download_whisper_model_custom_name(self, tmp_path):
        """Test downloading custom model name."""
        model_dir = tmp_path / "whisper"
        fake_model = MagicMock()
        
        with patch('src.transcription.get_whisper_model_directory', return_value=model_dir), \
             patch('src.transcription.whisper.load_model', return_value=fake_model) as mock_load, \
             patch('src.transcription.print_flush'):
            
            download_whisper_model("large")
            mock_load.assert_called_once_with("large", download_root=str(model_dir))
    
    def test_download_whisper_model_failure(self, tmp_path):
        """Test model download failure."""
        model_dir = tmp_path / "whisper"
        
        with patch('src.transcription.get_whisper_model_directory', return_value=model_dir), \
             patch('src.transcription.whisper.load_model', side_effect=Exception("Download failed")), \
             patch('src.transcription.print_flush'), \
             pytest.raises(Exception, match="Download failed"):
            
            download_whisper_model("base")
    
    def test_download_whisper_model_environment_cleanup(self, tmp_path):
        """Test that environment variables are properly cleaned up."""
        model_dir = tmp_path / "whisper"
        fake_model = MagicMock()
        
        # Set an original cache variable
        original_env = os.environ.get('XDG_CACHE_HOME')
        os.environ['XDG_CACHE_HOME'] = '/original/cache'
        
        try:
            with patch('src.transcription.get_whisper_model_directory', return_value=model_dir), \
                 patch('src.transcription.whisper.load_model', return_value=fake_model), \
                 patch('src.transcription.print_flush'):
                
                download_whisper_model("base")
                
                # Environment should be restored
                assert os.environ.get('XDG_CACHE_HOME') == '/original/cache'
        finally:
            # Cleanup
            if original_env:
                os.environ['XDG_CACHE_HOME'] = original_env
            elif 'XDG_CACHE_HOME' in os.environ:
                del os.environ['XDG_CACHE_HOME']


class TestGetWhisperModel:
    """Test Whisper model getting functionality."""
    
    def test_get_whisper_model_cached(self, tmp_path):
        """Test loading cached model."""
        model_dir = tmp_path / "whisper"
        fake_model = MagicMock()
        
        with patch('src.transcription.get_whisper_model_directory', return_value=model_dir), \
             patch('src.transcription.whisper.load_model', return_value=fake_model) as mock_load, \
             patch('src.transcription.print_flush'), \
             patch('src.transcription.Config') as mock_config:
            
            mock_config.WHISPER_MODEL = "base"
            result = get_whisper_model("base")
            
            assert result == fake_model
            mock_load.assert_called_once()
    
    def test_get_whisper_model_not_cached(self, tmp_path):
        """Test downloading model when not cached."""
        model_dir = tmp_path / "whisper"
        fake_model = MagicMock()
        
        with patch('src.transcription.get_whisper_model_directory', return_value=model_dir), \
             patch('src.transcription.whisper.load_model', side_effect=[Exception("Not found"), fake_model]), \
             patch('src.transcription.download_whisper_model', return_value=fake_model) as mock_download, \
             patch('src.transcription.print_flush'):
            
            result = get_whisper_model("base")
            
            assert result == fake_model
            mock_download.assert_called_once_with("base")


class TestTranscribeVideo:
    """Test video transcription functionality."""
    
    def test_transcribe_video_success(self, tmp_path):
        """Test successful video transcription."""
        video_file = tmp_path / "test.mp4"
        video_file.write_text("fake video")
        
        fake_model = MagicMock()
        fake_model.transcribe.return_value = {"text": "Hello world"}
        
        # Mock ffprobe to indicate audio stream exists
        mock_ffprobe = MagicMock()
        mock_ffprobe.stdout = "aac"
        
        with patch('src.transcription.get_whisper_model', return_value=fake_model), \
             patch('subprocess.run', return_value=mock_ffprobe), \
             patch('src.transcription.print_flush'):
            
            result = transcribe_video(str(video_file))
            assert result == "Hello world"
            fake_model.transcribe.assert_called_once_with(str(video_file))
    
    def test_transcribe_video_no_audio_stream(self, tmp_path):
        """Test transcription when video has no audio stream."""
        video_file = tmp_path / "test.mp4"
        video_file.write_text("fake video")
        
        # Mock ffprobe to indicate no audio stream
        mock_ffprobe = MagicMock()
        mock_ffprobe.stdout = ""
        
        with patch('subprocess.run', return_value=mock_ffprobe), \
             patch('src.transcription.print_flush'):
            
            result = transcribe_video(str(video_file))
            assert result == ""
    
    def test_transcribe_video_file_not_found(self):
        """Test transcription when video file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            transcribe_video("/nonexistent/video.mp4")
    
    def test_transcribe_video_whisper_audio_error(self, tmp_path):
        """Test transcription when Whisper can't load audio."""
        video_file = tmp_path / "test.mp4"
        video_file.write_text("fake video")
        
        fake_model = MagicMock()
        fake_model.transcribe.side_effect = Exception("Failed to load audio does not contain any stream")
        
        mock_ffprobe = MagicMock()
        mock_ffprobe.stdout = "aac"
        
        with patch('src.transcription.get_whisper_model', return_value=fake_model), \
             patch('subprocess.run', return_value=mock_ffprobe), \
             patch('src.transcription.print_flush'):
            
            result = transcribe_video(str(video_file))
            assert result == ""
    
    def test_transcribe_video_other_error(self, tmp_path):
        """Test transcription with other errors."""
        video_file = tmp_path / "test.mp4"
        video_file.write_text("fake video")
        
        fake_model = MagicMock()
        fake_model.transcribe.side_effect = Exception("Some other error")
        
        mock_ffprobe = MagicMock()
        mock_ffprobe.stdout = "aac"
        
        with patch('src.transcription.get_whisper_model', return_value=fake_model), \
             patch('subprocess.run', return_value=mock_ffprobe), \
             patch('src.transcription.print_flush'), \
             pytest.raises(Exception, match="Some other error"):
            
            transcribe_video(str(video_file))


class TestParseSubtitleFile:
    """Test subtitle file parsing functionality."""
    
    def test_parse_subtitle_file_vtt(self, tmp_path):
        """Test parsing VTT subtitle file."""
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:03.000
Hello world, this is a test transcript.

00:00:03.000 --> 00:00:06.000
This is the second line of text.

00:00:06.000 --> 00:00:10.000
<v Speaker>And this has HTML tags to remove.</v>
"""
        vtt_file = tmp_path / "test.vtt"
        vtt_file.write_text(vtt_content, encoding='utf-8')
        
        result = parse_subtitle_file(str(vtt_file))
        expected = "Hello world, this is a test transcript. This is the second line of text. And this has HTML tags to remove."
        assert result == expected
    
    def test_parse_subtitle_file_srt(self, tmp_path):
        """Test parsing SRT subtitle file."""
        srt_content = """1
00:00:00,000 --> 00:00:03,000
Hello world

2
00:00:03,000 --> 00:00:06,000
Second subtitle
"""
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(srt_content, encoding='utf-8')
        
        result = parse_subtitle_file(str(srt_file))
        expected = "Hello world Second subtitle"
        assert result == expected
    
    def test_parse_subtitle_file_empty(self, tmp_path):
        """Test parsing empty subtitle file."""
        empty_file = tmp_path / "empty.vtt"
        empty_file.write_text("WEBVTT\n\n", encoding='utf-8')
        
        result = parse_subtitle_file(str(empty_file))
        assert result == ""
    
    def test_parse_subtitle_file_error(self):
        """Test parsing non-existent file."""
        result = parse_subtitle_file("/nonexistent/file.vtt")
        assert result == ""
    
    def test_parse_subtitle_file_html_removal(self, tmp_path):
        """Test HTML tag removal."""
        content_with_html = """WEBVTT

00:00:00.000 --> 00:00:03.000
<b>Bold text</b> and <i>italic text</i>

00:00:03.000 --> 00:00:06.000
<span style="color: red;">Colored text</span>
"""
        html_file = tmp_path / "html.vtt"
        html_file.write_text(content_with_html, encoding='utf-8')
        
        result = parse_subtitle_file(str(html_file))
        expected = "Bold text and italic text Colored text"
        assert result == expected


class TestExtractTranscriptFromPlatform:
    """Test platform transcript extraction functionality."""
    
    def test_extract_transcript_from_platform_success(self, tmp_path):
        """Test successful transcript extraction."""
        subtitle_dir = tmp_path / "subtitles"
        subtitle_dir.mkdir()
        
        # Create a mock subtitle file
        subtitle_file = subtitle_dir / "test.en.vtt"
        subtitle_file.write_text("""WEBVTT

00:00:00.000 --> 00:00:03.000
Platform provided transcript
""", encoding='utf-8')
        
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {
            'title': 'Test Video',
            'subtitles': {'en': [{'url': 'fake_url'}]}
        }
        
        with patch('src.transcription.yt_dlp.YoutubeDL') as mock_ydl_class, \
             patch('src.transcription.print_flush'), \
             patch('os.makedirs'), \
             patch('os.listdir', return_value=['test.en.vtt']):
            
            mock_ydl_class.return_value.__enter__.return_value = mock_ydl
            
            # Mock parse_subtitle_file to return expected text
            with patch('src.transcription.parse_subtitle_file', return_value="Platform provided transcript"):
                result = extract_transcript_from_platform("https://test.com/video", str(tmp_path))
                assert result == "Platform provided transcript"
    
    def test_extract_transcript_from_platform_no_subtitles(self, tmp_path):
        """Test when no subtitles are available."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {
            'title': 'Test Video'
            # No subtitles or automatic_captions
        }
        
        with patch('src.transcription.yt_dlp.YoutubeDL') as mock_ydl_class, \
             patch('src.transcription.print_flush'), \
             patch('os.makedirs'), \
             patch('os.listdir', return_value=[]):
            
            mock_ydl_class.return_value.__enter__.return_value = mock_ydl
            
            result = extract_transcript_from_platform("https://test.com/video", str(tmp_path))
            assert result is None
    
    def test_extract_transcript_from_platform_empty_transcript(self, tmp_path):
        """Test when transcript file is empty."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {
            'title': 'Test Video',
            'subtitles': {'en': [{'url': 'fake_url'}]}
        }
        
        with patch('src.transcription.yt_dlp.YoutubeDL') as mock_ydl_class, \
             patch('src.transcription.print_flush'), \
             patch('os.makedirs'), \
             patch('os.listdir', return_value=['test.en.vtt']):
            
            mock_ydl_class.return_value.__enter__.return_value = mock_ydl
            
            # Mock parse_subtitle_file to return empty string
            with patch('src.transcription.parse_subtitle_file', return_value=""):
                result = extract_transcript_from_platform("https://test.com/video", str(tmp_path))
                assert result is None
    
    def test_extract_transcript_from_platform_error(self, tmp_path):
        """Test when yt-dlp raises an error."""
        with patch('src.transcription.yt_dlp.YoutubeDL') as mock_ydl_class, \
             patch('src.transcription.print_flush'):
            
            mock_ydl_class.side_effect = Exception("Network error")
            
            result = extract_transcript_from_platform("https://test.com/video", str(tmp_path))
            assert result is None