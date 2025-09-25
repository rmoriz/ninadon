#!/usr/bin/env python3
"""Tests for video_processing module."""

import os
import pytest
from unittest.mock import MagicMock, patch
from src.video_processing import maybe_reencode


class TestMaybeReencode:
    """Test video re-encoding functionality."""
    
    def test_maybe_reencode_small_file(self, tmp_path):
        """Test that small files are not re-encoded."""
        # Create a small video file (10MB)
        video_file = tmp_path / "small_video.mp4"
        video_content = b"0" * (10 * 1024 * 1024)  # 10MB
        video_file.write_bytes(video_content)
        
        result = maybe_reencode(str(video_file), str(tmp_path))
        
        # Should return original path since file is under 25MB
        assert result == str(video_file)
    
    def test_maybe_reencode_large_file(self, tmp_path):
        """Test that large files are re-encoded."""
        # Create a large video file (30MB)
        video_file = tmp_path / "large_video.mp4"
        video_content = b"0" * (30 * 1024 * 1024)  # 30MB
        video_file.write_bytes(video_content)
        
        expected_output = tmp_path / "video_h265.mp4"
        
        with patch('subprocess.run') as mock_run, \
             patch('src.video_processing.print_flush'), \
             patch('src.video_processing.Config') as mock_config:
            
            mock_config.TRANSCODE_TIMEOUT = 600
            
            result = maybe_reencode(str(video_file), str(tmp_path))
            
            # Should return new path
            assert result == str(expected_output)
            
            # Verify ffmpeg was called with correct parameters
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]  # First positional argument
            
            expected_cmd = [
                "ffmpeg", "-i", str(video_file), "-c:v", "libx265", 
                "-crf", "35", "-c:a", "copy", str(expected_output)
            ]
            assert call_args == expected_cmd
            
            # Verify timeout was passed
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs['timeout'] == 600
    
    def test_maybe_reencode_exactly_25mb(self, tmp_path):
        """Test file exactly at 25MB threshold."""
        # Create a file exactly 25MB
        video_file = tmp_path / "exact_25mb.mp4"
        video_content = b"0" * (25 * 1024 * 1024)  # Exactly 25MB
        video_file.write_bytes(video_content)
        
        result = maybe_reencode(str(video_file), str(tmp_path))
        
        # Should return original path (not re-encoded since it's not > 25MB)
        assert result == str(video_file)
    
    def test_maybe_reencode_just_over_25mb(self, tmp_path):
        """Test file just over 25MB threshold."""
        # Create a file just over 25MB
        video_file = tmp_path / "just_over_25mb.mp4"
        video_content = b"0" * (25 * 1024 * 1024 + 1)  # 25MB + 1 byte
        video_file.write_bytes(video_content)
        
        expected_output = tmp_path / "video_h265.mp4"
        
        with patch('subprocess.run') as mock_run, \
             patch('src.video_processing.print_flush'), \
             patch('src.video_processing.Config') as mock_config:
            
            mock_config.TRANSCODE_TIMEOUT = 600
            
            result = maybe_reencode(str(video_file), str(tmp_path))
            
            # Should be re-encoded
            assert result == str(expected_output)
            mock_run.assert_called_once()
    
    def test_maybe_reencode_custom_timeout(self, tmp_path):
        """Test re-encoding with custom timeout."""
        # Create a large video file
        video_file = tmp_path / "large_video.mp4"
        video_content = b"0" * (30 * 1024 * 1024)  # 30MB
        video_file.write_bytes(video_content)
        
        with patch('subprocess.run') as mock_run, \
             patch('src.video_processing.print_flush'), \
             patch('src.video_processing.Config') as mock_config:
            
            mock_config.TRANSCODE_TIMEOUT = 1200  # Custom timeout
            
            maybe_reencode(str(video_file), str(tmp_path))
            
            # Verify custom timeout was used
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs['timeout'] == 1200
    
    def test_maybe_reencode_ffmpeg_error(self, tmp_path):
        """Test handling of ffmpeg errors."""
        # Create a large video file
        video_file = tmp_path / "large_video.mp4"
        video_content = b"0" * (30 * 1024 * 1024)  # 30MB
        video_file.write_bytes(video_content)
        
        with patch('subprocess.run', side_effect=Exception("ffmpeg failed")) as mock_run, \
             patch('src.video_processing.print_flush'), \
             patch('src.video_processing.Config') as mock_config, \
             pytest.raises(Exception, match="ffmpeg failed"):
            
            mock_config.TRANSCODE_TIMEOUT = 600
            maybe_reencode(str(video_file), str(tmp_path))
    
    def test_maybe_reencode_output_path_generation(self, tmp_path):
        """Test that output path is correctly generated."""
        # Create a large video file in subdirectory
        subdir = tmp_path / "videos"
        subdir.mkdir()
        video_file = subdir / "test_video.mp4"
        video_content = b"0" * (30 * 1024 * 1024)  # 30MB
        video_file.write_bytes(video_content)
        
        with patch('subprocess.run') as mock_run, \
             patch('src.video_processing.print_flush'), \
             patch('src.video_processing.Config') as mock_config:
            
            mock_config.TRANSCODE_TIMEOUT = 600
            
            result = maybe_reencode(str(video_file), str(tmp_path))
            
            # Output should be in the tmpdir, not the subdirectory
            expected_output = tmp_path / "video_h265.mp4"
            assert result == str(expected_output)
            
            # Verify ffmpeg output path
            call_args = mock_run.call_args[0][0]
            output_path = call_args[-1]  # Last argument is output path
            assert output_path == str(expected_output)
    
    def test_maybe_reencode_file_size_calculation(self, tmp_path):
        """Test file size calculation and logging."""
        # Create a video file with known size
        video_file = tmp_path / "test_video.mp4"
        size_bytes = 50 * 1024 * 1024  # 50MB
        video_content = b"0" * size_bytes
        video_file.write_bytes(video_content)
        
        with patch('subprocess.run') as mock_run, \
             patch('src.video_processing.print_flush') as mock_print, \
             patch('src.video_processing.Config') as mock_config:
            
            mock_config.TRANSCODE_TIMEOUT = 600
            
            maybe_reencode(str(video_file), str(tmp_path))
            
            # Verify size was calculated and logged correctly
            # Should log size as 50.00MB
            mock_print.assert_called()
            print_calls = [str(call) for call in mock_print.call_args_list]
            size_logged = any("50.00MB" in call for call in print_calls)
            assert size_logged
    
    def test_maybe_reencode_preserves_check_true_flag(self, tmp_path):
        """Test that subprocess.run is called with check=True."""
        # Create a large video file
        video_file = tmp_path / "large_video.mp4"
        video_content = b"0" * (30 * 1024 * 1024)  # 30MB
        video_file.write_bytes(video_content)
        
        with patch('subprocess.run') as mock_run, \
             patch('src.video_processing.print_flush'), \
             patch('src.video_processing.Config') as mock_config:
            
            mock_config.TRANSCODE_TIMEOUT = 600
            
            maybe_reencode(str(video_file), str(tmp_path))
            
            # Verify check=True was passed to subprocess.run
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs['check'] is True


class TestVideoProcessingIntegration:
    """Test video processing integration scenarios."""
    
    def test_reencode_workflow_large_to_small(self, tmp_path):
        """Test complete workflow from large file to re-encoded file."""
        # Simulate a large file that gets re-encoded to smaller size
        original_file = tmp_path / "large_original.mp4"
        original_content = b"0" * (50 * 1024 * 1024)  # 50MB
        original_file.write_bytes(original_content)
        
        reencoded_file = tmp_path / "video_h265.mp4"
        
        def mock_ffmpeg_call(*args, **kwargs):
            # Simulate ffmpeg creating a smaller output file
            smaller_content = b"0" * (15 * 1024 * 1024)  # 15MB
            reencoded_file.write_bytes(smaller_content)
        
        with patch('subprocess.run', side_effect=mock_ffmpeg_call), \
             patch('src.video_processing.print_flush'), \
             patch('src.video_processing.Config') as mock_config:
            
            mock_config.TRANSCODE_TIMEOUT = 600
            
            result = maybe_reencode(str(original_file), str(tmp_path))
            
            # Should return the re-encoded file path
            assert result == str(reencoded_file)
            
            # Verify the re-encoded file exists and is smaller
            assert reencoded_file.exists()
            assert reencoded_file.stat().st_size < original_file.stat().st_size
    
    def test_no_reencode_workflow(self, tmp_path):
        """Test workflow when file doesn't need re-encoding."""
        # Create a small file
        small_file = tmp_path / "small_video.mp4"
        small_content = b"0" * (10 * 1024 * 1024)  # 10MB
        small_file.write_bytes(small_content)
        
        with patch('subprocess.run') as mock_run, \
             patch('src.video_processing.print_flush'):
            
            result = maybe_reencode(str(small_file), str(tmp_path))
            
            # Should return original file
            assert result == str(small_file)
            
            # ffmpeg should not have been called
            mock_run.assert_not_called()
            
            # Original file should be unchanged
            assert small_file.exists()
            assert small_file.stat().st_size == len(small_content)