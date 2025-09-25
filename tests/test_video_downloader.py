#!/usr/bin/env python3
"""Tests for video_downloader module."""

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from src.video_downloader import (
    collect_formats, build_candidates, select_filepath, 
    fix_downloaded_filepath, determine_platform, extract_hashtags,
    download_video, run_ydl
)


class TestCollectFormats:
    """Test format collection functionality."""
    
    def test_collect_formats_basic(self):
        """Test basic format collection."""
        formats = [
            {'url': 'http://test.com/1', 'filesize': 1000, 'vcodec': 'avc1', 'acodec': 'mp4a', 'format_id': '1'},
            {'url': 'http://test.com/2', 'filesize': 2000, 'vcodec': 'avc1', 'acodec': 'none', 'format_id': '2'},
            {'url': 'http://test.com/3', 'filesize': 3000, 'vcodec': 'none', 'acodec': 'mp4a', 'format_id': '3'},
        ]
        
        muxed, videos, audios = collect_formats(formats)
        
        assert len(muxed) == 1
        assert len(videos) == 1
        assert len(audios) == 1
        assert muxed[0][1]['format_id'] == '1'
        assert videos[0][1]['format_id'] == '2'
        assert audios[0][1]['format_id'] == '3'
    
    def test_collect_formats_no_url(self):
        """Test formats without URLs are ignored."""
        formats = [
            {'filesize': 1000, 'vcodec': 'avc1', 'acodec': 'mp4a', 'format_id': '1'},  # No URL
            {'url': 'http://test.com/2', 'vcodec': 'avc1', 'acodec': 'mp4a', 'format_id': '2'},  # No filesize
            {'url': 'http://test.com/3', 'filesize': 3000, 'vcodec': 'avc1', 'acodec': 'mp4a', 'format_id': '3'},
        ]
        
        muxed, videos, audios = collect_formats(formats)
        assert len(muxed) == 1
        assert muxed[0][1]['format_id'] == '3'
    
    def test_collect_formats_filesize_approx(self):
        """Test formats with filesize_approx."""
        formats = [
            {'url': 'http://test.com/1', 'filesize_approx': 1000, 'vcodec': 'avc1', 'acodec': 'mp4a', 'format_id': '1'},
        ]
        
        muxed, videos, audios = collect_formats(formats)
        assert len(muxed) == 1
        assert muxed[0][0] == 1000


class TestBuildCandidates:
    """Test candidate building functionality."""
    
    def test_build_candidates_muxed_only(self):
        """Test building candidates with only muxed formats."""
        muxed = [(1000, {'format_id': '1'}), (2000, {'format_id': '2'})]
        videos = []
        audios = []
        
        candidates = build_candidates(muxed, videos, audios)
        assert len(candidates) == 2
        assert candidates[0] == (1000, '1')
        assert candidates[1] == (2000, '2')
    
    def test_build_candidates_with_separate_streams(self):
        """Test building candidates with separate video/audio streams."""
        muxed = [(1000, {'format_id': 'muxed1'})]
        videos = [(800, {'format_id': 'video1'}), (1200, {'format_id': 'video2'})]
        audios = [(200, {'format_id': 'audio1'})]
        
        candidates = build_candidates(muxed, videos, audios)
        
        # Should have 1 muxed + 2 video+audio combinations
        assert len(candidates) == 3
        assert (1000, 'muxed1') in candidates
        assert (1000, 'video1+audio1') in candidates  # 800 + 200
        assert (1400, 'video2+audio1') in candidates  # 1200 + 200


class TestSelectFilepath:
    """Test filepath selection functionality."""
    
    def test_select_filepath_requested_downloads(self):
        """Test filepath selection with requested_downloads."""
        info = {'requested_downloads': [{'filepath': '/path/to/video.mp4'}]}
        ydl = MagicMock()
        
        result = select_filepath(info, ydl)
        assert result == '/path/to/video.mp4'
        ydl.prepare_filename.assert_not_called()
    
    def test_select_filepath_prepare_filename(self):
        """Test filepath selection using prepare_filename."""
        info = {}
        ydl = MagicMock()
        ydl.prepare_filename.return_value = '/prepared/path.mp4'
        
        result = select_filepath(info, ydl)
        assert result == '/prepared/path.mp4'
        ydl.prepare_filename.assert_called_once_with(info)


class TestFixDownloadedFilepath:
    """Test filepath fixing functionality."""
    
    def test_fix_downloaded_filepath_exists(self):
        """Test when file exists as-is."""
        with patch('os.path.exists', return_value=True):
            result = fix_downloaded_filepath('/path/video.mp4', '/tmp')
            assert result == '/path/video.mp4'
    
    def test_fix_downloaded_filepath_search_directory(self, tmp_path):
        """Test searching directory for video files."""
        # Create a video file in the temp directory
        video_file = tmp_path / "video_test.mp4"
        video_file.write_text("fake video")
        
        result = fix_downloaded_filepath(None, str(tmp_path))
        assert result == str(video_file)
    
    def test_fix_downloaded_filepath_na_extension(self, tmp_path):
        """Test handling .NA extension."""
        na_file = tmp_path / "video.NA"
        na_file.write_text("fake video")
        
        # Mock ffprobe to return format info
        mock_result = MagicMock()
        mock_result.stdout = '{"format": {"format_name": "mp4,mov"}}'
        
        with patch('subprocess.run', return_value=mock_result), \
             patch('os.rename') as mock_rename:
            
            result = fix_downloaded_filepath(str(na_file), str(tmp_path))
            expected_new_path = str(tmp_path / "video.mp4")
            mock_rename.assert_called_once_with(str(na_file), expected_new_path)
            assert result == expected_new_path
    
    def test_fix_downloaded_filepath_no_files_found(self, tmp_path):
        """Test when no video files are found."""
        with pytest.raises(FileNotFoundError, match="No video file found"):
            fix_downloaded_filepath(None, str(tmp_path))


class TestDeterminePlatform:
    """Test platform determination functionality."""
    
    def test_determine_platform_tiktok(self):
        """Test TikTok platform detection."""
        assert determine_platform("https://www.tiktok.com/@user/video/123") == "tiktok"
        assert determine_platform("https://TIKTOK.COM/video/456") == "tiktok"
    
    def test_determine_platform_youtube(self):
        """Test YouTube platform detection."""
        assert determine_platform("https://www.youtube.com/watch?v=123") == "youtube"
        assert determine_platform("https://youtu.be/456") == "youtube"
        assert determine_platform("https://YOUTUBE.com/watch?v=789") == "youtube"
    
    def test_determine_platform_instagram(self):
        """Test Instagram platform detection."""
        assert determine_platform("https://www.instagram.com/p/123/") == "instagram"
        assert determine_platform("https://INSTAGRAM.COM/reel/456/") == "instagram"
    
    def test_determine_platform_unknown(self):
        """Test unknown platform detection."""
        assert determine_platform("https://example.com/video/123") == "unknown"
        assert determine_platform("https://vimeo.com/123456") == "unknown"


class TestExtractHashtags:
    """Test hashtag extraction functionality."""
    
    def test_extract_hashtags_basic(self):
        """Test basic hashtag extraction."""
        title = "Amazing video #amazing #cool"
        description = "Check this out! #viral #trending"
        
        hashtags = extract_hashtags(title, description)
        expected = ['#amazing', '#cool', '#viral', '#trending']
        
        # Sort both lists since order doesn't matter
        assert sorted(hashtags) == sorted(expected)
    
    def test_extract_hashtags_duplicates(self):
        """Test hashtag extraction removes duplicates."""
        title = "Video #test #cool"
        description = "Description #test #awesome"
        
        hashtags = extract_hashtags(title, description)
        assert '#test' in hashtags
        assert hashtags.count('#test') == 1  # Should appear only once
    
    def test_extract_hashtags_no_hashtags(self):
        """Test extraction when no hashtags present."""
        title = "Regular video title"
        description = "Regular description without hashtags"
        
        hashtags = extract_hashtags(title, description)
        assert hashtags == []
    
    def test_extract_hashtags_mixed_case(self):
        """Test hashtag extraction with mixed case."""
        title = "Video #Test #COOL"
        description = "Description #test #Cool"
        
        hashtags = extract_hashtags(title, description)
        # Should preserve original case and treat as different
        assert len(hashtags) == 4


class TestRunYdl:
    """Test yt-dlp runner functionality."""
    
    def test_run_ydl_basic(self):
        """Test basic yt-dlp execution."""
        fake_info = {'title': 'Test Video'}
        
        with patch('src.video_downloader.yt_dlp.YoutubeDL') as mock_ydl_class:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = fake_info
            mock_ydl_class.return_value.__enter__.return_value = mock_ydl
            
            info, ydl = run_ydl('https://test.com/video', {'quiet': True}, False)
            
            assert info == fake_info
            assert ydl == mock_ydl
            mock_ydl.extract_info.assert_called_once_with('https://test.com/video', download=False)


class TestDownloadVideo:
    """Test main download_video functionality."""
    
    def test_download_video_mock(self, tmp_path):
        """Test download_video with mocked dependencies."""
        # Mock the video file
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video content")
        
        fake_info = {
            'formats': [
                {'url': 'http://test.com/1', 'filesize': 10*1024*1024, 'vcodec': 'avc1', 'acodec': 'mp4a', 'format_id': '1'}
            ],
            'title': 'Test Video',
            'description': 'Test description #hashtag',
            'uploader': 'testuser',
            'requested_downloads': [{'filepath': str(video_file)}]
        }
        
        with patch('src.video_downloader.run_ydl') as mock_run_ydl:
            # First call (info extraction) returns info without download
            # Second call (actual download) returns info with download
            mock_run_ydl.side_effect = [
                (fake_info, MagicMock()),  # Info extraction
                (fake_info, MagicMock())   # Download
            ]
            
            result = download_video('https://test.com/video', str(tmp_path))
            
            filepath, title, description, uploader, hashtags, platform, mime_type = result
            
            assert filepath == str(video_file)
            assert title == 'Test Video'
            assert description == 'Test description #hashtag'
            assert uploader == 'testuser'
            assert hashtags == ['#hashtag']
            assert platform == "unknown"  # test.com is not a known platform
    
    def test_download_video_format_selection(self, tmp_path):
        """Test format selection logic in download_video."""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video content")
        
        # Create formats where one is under 30MB
        fake_info = {
            'formats': [
                {'url': 'http://test.com/1', 'filesize': 50*1024*1024, 'vcodec': 'avc1', 'acodec': 'mp4a', 'format_id': 'large'},
                {'url': 'http://test.com/2', 'filesize': 10*1024*1024, 'vcodec': 'avc1', 'acodec': 'mp4a', 'format_id': 'small'}
            ],
            'title': 'Test Video',
            'description': 'Test description',
            'uploader': 'testuser',
            'requested_downloads': [{'filepath': str(video_file)}]
        }
        
        with patch('src.video_downloader.run_ydl') as mock_run_ydl:
            mock_run_ydl.side_effect = [
                (fake_info, MagicMock()),  # Info extraction
                (fake_info, MagicMock())   # Download with selected format
            ]
            
            download_video('https://test.com/video', str(tmp_path))
            
            # Check that the second call used the smaller format
            assert mock_run_ydl.call_count == 2
            download_call_args = mock_run_ydl.call_args_list[1]
            ydl_opts = download_call_args[0][1]  # Second argument
            assert ydl_opts['format'] == 'small'