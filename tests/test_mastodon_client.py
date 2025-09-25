#!/usr/bin/env python3
"""Tests for mastodon_client module."""

import time
import pytest
from unittest.mock import MagicMock, patch
from src.mastodon_client import wait_for_media_processing, post_to_mastodon


class TestWaitForMediaProcessing:
    """Test media processing wait functionality."""
    
    def test_wait_for_media_processing_success(self):
        """Test successful media processing wait."""
        mock_mastodon = MagicMock()
        
        # Simulate processing -> complete sequence
        mock_mastodon.media.side_effect = [
            {"id": "media123", "processing": True},  # First call: still processing
            {"id": "media123", "processing": True},  # Second call: still processing
            {"id": "media123", "url": "http://mastodon.example.com/media/123", "processing": False}  # Third call: complete
        ]
        
        with patch('time.sleep') as mock_sleep:
            result = wait_for_media_processing(mock_mastodon, "media123", timeout=10, poll_interval=1)
            
            assert result["id"] == "media123"
            assert result["url"] == "http://mastodon.example.com/media/123"
            assert result["processing"] is False
            
            # Should have called media() 3 times
            assert mock_mastodon.media.call_count == 3
            
            # Should have slept twice (between the 3 calls)
            assert mock_sleep.call_count == 2
            mock_sleep.assert_called_with(1)  # poll_interval
    
    def test_wait_for_media_processing_immediate_success(self):
        """Test when media is immediately ready."""
        mock_mastodon = MagicMock()
        mock_mastodon.media.return_value = {
            "id": "media123", 
            "url": "http://mastodon.example.com/media/123", 
            "processing": False
        }
        
        with patch('time.sleep') as mock_sleep:
            result = wait_for_media_processing(mock_mastodon, "media123")
            
            assert result["url"] == "http://mastodon.example.com/media/123"
            
            # Should only call media() once
            assert mock_mastodon.media.call_count == 1
            
            # Should not sleep since it was immediately ready
            mock_sleep.assert_not_called()
    
    def test_wait_for_media_processing_timeout(self):
        """Test timeout when media processing takes too long."""
        mock_mastodon = MagicMock()
        mock_mastodon.media.return_value = {
            "id": "media123", 
            "processing": True  # Always processing
        }
        
        with patch('time.sleep'), \
             patch('time.time', side_effect=[0, 1, 2, 3, 4, 5, 6]), \
             patch('src.mastodon_client.print_flush'), \
             pytest.raises(RuntimeError, match="Media processing timed out"):
            
            wait_for_media_processing(mock_mastodon, "media123", timeout=5, poll_interval=1)
    
    def test_wait_for_media_processing_default_timeout(self):
        """Test using default timeout from config."""
        mock_mastodon = MagicMock()
        mock_mastodon.media.return_value = {
            "id": "media123",
            "url": "http://example.com/media",
            "processing": False
        }
        
        with patch('src.mastodon_client.Config') as mock_config:
            mock_config.MASTODON_MEDIA_TIMEOUT = 1200
            
            wait_for_media_processing(mock_mastodon, "media123")
            
            # Should use config timeout (this test mainly ensures no error occurs)
            assert mock_mastodon.media.call_count == 1
    
    def test_wait_for_media_processing_no_url(self):
        """Test when media has no URL but processing is False."""
        mock_mastodon = MagicMock()
        mock_mastodon.media.side_effect = [
            {"id": "media123", "processing": False},  # No URL field, but not processing
            {"id": "media123", "url": "http://example.com/media", "processing": False}  # Gets URL on second call
        ]
        
        with patch('time.sleep'):
            result = wait_for_media_processing(mock_mastodon, "media123", timeout=10)
            
            assert result["url"] == "http://example.com/media"
            assert mock_mastodon.media.call_count == 2
    
    def test_wait_for_media_processing_custom_poll_interval(self):
        """Test custom poll interval."""
        mock_mastodon = MagicMock()
        mock_mastodon.media.side_effect = [
            {"id": "media123", "processing": True},
            {"id": "media123", "url": "http://example.com/media", "processing": False}
        ]
        
        with patch('time.sleep') as mock_sleep:
            wait_for_media_processing(mock_mastodon, "media123", timeout=10, poll_interval=5)
            
            mock_sleep.assert_called_once_with(5)


class TestPostToMastodon:
    """Test Mastodon posting functionality."""
    
    def test_post_to_mastodon_success(self, tmp_path):
        """Test successful posting to Mastodon."""
        # Create a test video file
        video_file = tmp_path / "test_video.mp4"
        video_file.write_bytes(b"fake video content")
        
        mock_config = MagicMock()
        mock_config.MASTODON_ACCESS_TOKEN = "test_token"
        mock_config.MASTODON_BASE_URL = "https://mastodon.example.com"
        
        mock_mastodon = MagicMock()
        mock_mastodon.media_post.return_value = {"id": "media123"}
        mock_mastodon.media.return_value = {
            "id": "media123",
            "url": "http://mastodon.example.com/media/123",
            "processing": False
        }
        mock_mastodon.status_post.return_value = {
            "url": "http://mastodon.example.com/status/456"
        }
        
        with patch('src.mastodon_client.Config') as mock_config_class, \
             patch('src.mastodon_client.Mastodon', return_value=mock_mastodon), \
             patch('src.mastodon_client.print_flush'):
            
            mock_config_class.MASTODON_MEDIA_TIMEOUT = 600
            mock_config_class.return_value = mock_config
            
            result = post_to_mastodon(
                "Test summary", 
                str(video_file), 
                "https://example.com/video", 
                "video/mp4", 
                "Video description for accessibility"
            )
            
            assert result == "http://mastodon.example.com/status/456"
            
            # Verify Mastodon instance was created correctly
            from src.mastodon_client import Mastodon
            Mastodon.assert_called_once_with(
                access_token="test_token",
                api_base_url="https://mastodon.example.com"
            )
            
            # Verify media upload
            mock_mastodon.media_post.assert_called_once_with(
                str(video_file), 
                mime_type="video/mp4", 
                description="Video description for accessibility"
            )
            
            # Verify status post
            expected_status = "Test summary\n\nSource: https://example.com/video"
            mock_mastodon.status_post.assert_called_once_with(
                expected_status, 
                media_ids=["media123"]
            )
    
    def test_post_to_mastodon_media_processing_wait(self, tmp_path):
        """Test posting with media processing wait."""
        video_file = tmp_path / "test_video.mp4"
        video_file.write_bytes(b"fake video content")
        
        mock_config = MagicMock()
        mock_config.MASTODON_ACCESS_TOKEN = "test_token"
        mock_config.MASTODON_BASE_URL = "https://mastodon.example.com"
        
        mock_mastodon = MagicMock()
        mock_mastodon.media_post.return_value = {"id": "media123"}
        
        # Simulate media processing sequence
        mock_mastodon.media.side_effect = [
            {"id": "media123", "processing": True},  # Still processing
            {"id": "media123", "url": "http://example.com/media", "processing": False}  # Ready
        ]
        
        mock_mastodon.status_post.return_value = {
            "url": "http://mastodon.example.com/status/456"
        }
        
        with patch('src.mastodon_client.Config') as mock_config_class, \
             patch('src.mastodon_client.Mastodon', return_value=mock_mastodon), \
             patch('src.mastodon_client.print_flush'), \
             patch('time.sleep'):
            
            mock_config_class.MASTODON_MEDIA_TIMEOUT = 600
            mock_config_class.return_value = mock_config
            
            result = post_to_mastodon("Summary", str(video_file), "https://source.com", "video/mp4", "Description")
            
            assert result == "http://mastodon.example.com/status/456"
            
            # Should have called media() twice for processing wait
            assert mock_mastodon.media.call_count == 2
    
    def test_post_to_mastodon_no_mime_type(self, tmp_path):
        """Test posting without explicit mime type."""
        video_file = tmp_path / "test_video.mp4"
        video_file.write_bytes(b"fake video content")
        
        mock_config = MagicMock()
        mock_config.MASTODON_ACCESS_TOKEN = "test_token"
        mock_config.MASTODON_BASE_URL = "https://mastodon.example.com"
        
        mock_mastodon = MagicMock()
        mock_mastodon.media_post.return_value = {"id": "media123"}
        mock_mastodon.media.return_value = {
            "id": "media123",
            "url": "http://example.com/media",
            "processing": False
        }
        mock_mastodon.status_post.return_value = {"url": "http://example.com/status"}
        
        with patch('src.mastodon_client.Config') as mock_config_class, \
             patch('src.mastodon_client.Mastodon', return_value=mock_mastodon), \
             patch('src.mastodon_client.print_flush'):
            
            mock_config_class.MASTODON_MEDIA_TIMEOUT = 600
            mock_config_class.return_value = mock_config
            
            post_to_mastodon("Summary", str(video_file), "https://source.com", None, "Description")
            
            # Should call media_post with mime_type=None
            mock_mastodon.media_post.assert_called_once_with(
                str(video_file), 
                mime_type=None, 
                description="Description"
            )
    
    def test_post_to_mastodon_long_summary(self, tmp_path):
        """Test posting with very long summary."""
        video_file = tmp_path / "test_video.mp4"
        video_file.write_bytes(b"fake video content")
        
        mock_config = MagicMock()
        mock_config.MASTODON_ACCESS_TOKEN = "test_token"
        mock_config.MASTODON_BASE_URL = "https://mastodon.example.com"
        
        mock_mastodon = MagicMock()
        mock_mastodon.media_post.return_value = {"id": "media123"}
        mock_mastodon.media.return_value = {
            "id": "media123",
            "url": "http://example.com/media",
            "processing": False
        }
        mock_mastodon.status_post.return_value = {"url": "http://example.com/status"}
        
        long_summary = "A" * 400  # Very long summary
        source_url = "https://example.com/video"
        
        with patch('src.mastodon_client.Config') as mock_config_class, \
             patch('src.mastodon_client.Mastodon', return_value=mock_mastodon), \
             patch('src.mastodon_client.print_flush'):
            
            mock_config_class.MASTODON_MEDIA_TIMEOUT = 600
            mock_config_class.return_value = mock_config
            
            post_to_mastodon(long_summary, str(video_file), source_url, "video/mp4", "Description")
            
            # Verify the full status text was posted
            expected_status = f"{long_summary}\n\nSource: {source_url}"
            mock_mastodon.status_post.assert_called_once_with(
                expected_status, 
                media_ids=["media123"]
            )
    
    def test_post_to_mastodon_media_upload_error(self, tmp_path):
        """Test handling media upload errors."""
        video_file = tmp_path / "test_video.mp4"
        video_file.write_bytes(b"fake video content")
        
        mock_config = MagicMock()
        mock_config.MASTODON_ACCESS_TOKEN = "test_token"
        mock_config.MASTODON_BASE_URL = "https://mastodon.example.com"
        
        mock_mastodon = MagicMock()
        mock_mastodon.media_post.side_effect = Exception("Upload failed")
        
        with patch('src.mastodon_client.Config') as mock_config_class, \
             patch('src.mastodon_client.Mastodon', return_value=mock_mastodon), \
             patch('src.mastodon_client.print_flush'), \
             pytest.raises(Exception, match="Upload failed"):
            
            mock_config_class.return_value = mock_config
            
            post_to_mastodon("Summary", str(video_file), "https://source.com", "video/mp4", "Description")
    
    def test_post_to_mastodon_status_post_error(self, tmp_path):
        """Test handling status post errors."""
        video_file = tmp_path / "test_video.mp4"
        video_file.write_bytes(b"fake video content")
        
        mock_config = MagicMock()
        mock_config.MASTODON_ACCESS_TOKEN = "test_token"
        mock_config.MASTODON_BASE_URL = "https://mastodon.example.com"
        
        mock_mastodon = MagicMock()
        mock_mastodon.media_post.return_value = {"id": "media123"}
        mock_mastodon.media.return_value = {
            "id": "media123",
            "url": "http://example.com/media",
            "processing": False
        }
        mock_mastodon.status_post.side_effect = Exception("Status post failed")
        
        with patch('src.mastodon_client.Config') as mock_config_class, \
             patch('src.mastodon_client.Mastodon', return_value=mock_mastodon), \
             patch('src.mastodon_client.print_flush'), \
             pytest.raises(Exception, match="Status post failed"):
            
            mock_config_class.MASTODON_MEDIA_TIMEOUT = 600
            mock_config_class.return_value = mock_config
            
            post_to_mastodon("Summary", str(video_file), "https://source.com", "video/mp4", "Description")
    
    def test_post_to_mastodon_media_processing_timeout(self, tmp_path):
        """Test handling media processing timeout."""
        video_file = tmp_path / "test_video.mp4"
        video_file.write_bytes(b"fake video content")
        
        mock_config = MagicMock()
        mock_config.MASTODON_ACCESS_TOKEN = "test_token"
        mock_config.MASTODON_BASE_URL = "https://mastodon.example.com"
        
        mock_mastodon = MagicMock()
        mock_mastodon.media_post.return_value = {"id": "media123"}
        
        with patch('src.mastodon_client.Config') as mock_config_class, \
             patch('src.mastodon_client.Mastodon', return_value=mock_mastodon), \
             patch('src.mastodon_client.wait_for_media_processing', side_effect=RuntimeError("Timeout")), \
             patch('src.mastodon_client.print_flush'), \
             pytest.raises(RuntimeError, match="Timeout"):
            
            mock_config_class.return_value = mock_config
            
            post_to_mastodon("Summary", str(video_file), "https://source.com", "video/mp4", "Description")


class TestMastodonClientIntegration:
    """Test Mastodon client integration scenarios."""
    
    def test_complete_posting_workflow(self, tmp_path):
        """Test complete posting workflow from upload to status."""
        video_file = tmp_path / "integration_test.mp4"
        video_file.write_bytes(b"test video for integration")
        
        mock_config = MagicMock()
        mock_config.MASTODON_ACCESS_TOKEN = "integration_token"
        mock_config.MASTODON_BASE_URL = "https://mastodon.integration.test"
        
        mock_mastodon = MagicMock()
        
        # Simulate complete workflow
        mock_mastodon.media_post.return_value = {"id": "media_integration_123"}
        mock_mastodon.media.return_value = {
            "id": "media_integration_123",
            "url": "http://mastodon.integration.test/media/123",
            "processing": False
        }
        mock_mastodon.status_post.return_value = {
            "url": "http://mastodon.integration.test/status/integration_456",
            "id": "integration_456"
        }
        
        with patch('src.mastodon_client.Config') as mock_config_class, \
             patch('src.mastodon_client.Mastodon', return_value=mock_mastodon), \
             patch('src.mastodon_client.print_flush') as mock_print:
            
            mock_config_class.MASTODON_MEDIA_TIMEOUT = 600
            mock_config_class.return_value = mock_config
            
            result = post_to_mastodon(
                "Integration test summary",
                str(video_file),
                "https://integration.test/source",
                "video/mp4",
                "Integration test video description"
            )
            
            # Verify final result
            assert result == "http://mastodon.integration.test/status/integration_456"
            
            # Verify all steps were called
            mock_mastodon.media_post.assert_called_once()
            mock_mastodon.media.assert_called_once()
            mock_mastodon.status_post.assert_called_once()
            
            # Verify logging occurred
            assert mock_print.call_count >= 3  # Should have logged upload, processing, and posting
            
            # Verify status content
            status_call = mock_mastodon.status_post.call_args[0][0]
            assert "Integration test summary" in status_call
            assert "Source: https://integration.test/source" in status_call