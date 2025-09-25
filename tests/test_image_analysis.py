#!/usr/bin/env python3
"""Tests for image_analysis module."""

import os
import base64
import pytest
from unittest.mock import MagicMock, patch
from src.image_analysis import (
    get_video_duration, extract_still_images, encode_image_to_base64,
    analyze_images_with_openrouter
)


class TestGetVideoDuration:
    """Test video duration extraction functionality."""
    
    def test_get_video_duration_success(self):
        """Test successful duration extraction."""
        mock_result = MagicMock()
        mock_result.stdout = "120.5\n"
        
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            duration = get_video_duration("/path/to/video.mp4")
            
            assert duration == 120.5
            mock_run.assert_called_once_with([
                "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                "-of", "csv=p=0", "/path/to/video.mp4"
            ], capture_output=True, text=True, check=True)
    
    def test_get_video_duration_integer(self):
        """Test duration extraction with integer result."""
        mock_result = MagicMock()
        mock_result.stdout = "60"
        
        with patch('subprocess.run', return_value=mock_result):
            duration = get_video_duration("/path/to/video.mp4")
            assert duration == 60.0
    
    def test_get_video_duration_error(self):
        """Test duration extraction with subprocess error."""
        with patch('subprocess.run', side_effect=Exception("ffprobe error")), \
             pytest.raises(Exception):
            get_video_duration("/path/to/video.mp4")


class TestExtractStillImages:
    """Test still image extraction functionality."""
    
    def test_extract_still_images_success(self, tmp_path):
        """Test successful image extraction."""
        video_path = "/path/to/video.mp4"
        duration = 100.0  # 100 seconds
        
        # Expected timestamps: 0.5, 25.0, 50.0, 75.0, 99.5
        expected_timestamps = [0.5, 25.0, 50.0, 75.0, 99.5]
        
        with patch('src.image_analysis.get_video_duration', return_value=duration), \
             patch('subprocess.run') as mock_run, \
             patch('src.image_analysis.print_flush'):
            
            result = extract_still_images(video_path, str(tmp_path))
            
            # Should return 5 image paths
            assert len(result) == 5
            
            # Check that ffmpeg was called 5 times
            assert mock_run.call_count == 5
            
            # Check the timestamps used
            for i, call in enumerate(mock_run.call_args_list):
                args = call[0][0]  # First positional argument (command list)
                timestamp_arg = args[2]  # -ss argument value
                assert float(timestamp_arg) == expected_timestamps[i]
                
                # Check output path
                output_path = args[-1]
                expected_path = os.path.join(str(tmp_path), f"frame_{i:02d}.jpg")
                assert output_path == expected_path
    
    def test_extract_still_images_short_video(self, tmp_path):
        """Test image extraction from short video."""
        video_path = "/path/to/video.mp4"
        duration = 2.0  # 2 seconds

        # For 2s video, end timestamp should be max(2.0 - 0.5, 0.5) = 1.5
        expected_end = max(duration - 0.5, 0.5)  # Should be 1.5

        with patch('src.image_analysis.get_video_duration', return_value=duration), \
             patch('subprocess.run') as mock_run, \
             patch('src.image_analysis.print_flush'):

            extract_still_images(video_path, str(tmp_path))

            # Check the last timestamp (end timestamp)
            last_call_args = mock_run.call_args_list[-1][0][0]
            last_timestamp = float(last_call_args[2])
            assert last_timestamp == 1.5
    
    def test_extract_still_images_ffmpeg_error(self, tmp_path):
        """Test image extraction with ffmpeg error."""
        video_path = "/path/to/video.mp4"
        
        with patch('src.image_analysis.get_video_duration', return_value=100.0), \
             patch('subprocess.run', side_effect=Exception("ffmpeg error")), \
             patch('src.image_analysis.print_flush'), \
             pytest.raises(Exception):
            
            extract_still_images(video_path, str(tmp_path))


class TestEncodeImageToBase64:
    """Test image base64 encoding functionality."""
    
    def test_encode_image_to_base64_success(self, tmp_path):
        """Test successful image encoding."""
        # Create a fake image file
        image_file = tmp_path / "test.jpg"
        image_content = b"fake image data"
        image_file.write_bytes(image_content)
        
        result = encode_image_to_base64(str(image_file))
        
        # Verify the result is base64 encoded
        expected = base64.b64encode(image_content).decode('utf-8')
        assert result == expected
    
    def test_encode_image_to_base64_file_not_found(self):
        """Test encoding non-existent file."""
        with pytest.raises(FileNotFoundError):
            encode_image_to_base64("/nonexistent/image.jpg")
    
    def test_encode_image_to_base64_empty_file(self, tmp_path):
        """Test encoding empty image file."""
        empty_file = tmp_path / "empty.jpg"
        empty_file.write_bytes(b"")
        
        result = encode_image_to_base64(str(empty_file))
        assert result == ""


class TestAnalyzeImagesWithOpenrouter:
    """Test image analysis with OpenRouter functionality."""
    
    def test_analyze_images_with_openrouter_success(self, tmp_path):
        """Test successful image analysis."""
        # Create fake image files
        image_paths = []
        for i in range(3):
            image_file = tmp_path / f"image_{i}.jpg"
            image_file.write_bytes(f"fake image {i}".encode())
            image_paths.append(str(image_file))
        
        # Mock config
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.ENHANCE_MODEL = "test_model"
        mock_config.IMAGE_ANALYSIS_PROMPT = "Test prompt"
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Analysis result"}}]
        }
        
        with patch('src.image_analysis.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response) as mock_post, \
             patch('src.image_analysis.encode_image_to_base64') as mock_encode:
            
            # Mock base64 encoding
            mock_encode.side_effect = lambda path: f"base64_data_for_{os.path.basename(path)}"
            
            result = analyze_images_with_openrouter(image_paths)
            
            assert result == "Analysis result"
            mock_post.assert_called_once()
            
            # Verify the request structure
            call_args = mock_post.call_args
            request_data = call_args[1]['json']
            
            assert request_data['model'] == "test_model"
            assert len(request_data['messages']) == 1
            
            message_content = request_data['messages'][0]['content']
            assert len(message_content) == 4  # 1 text + 3 images
            assert message_content[0]['type'] == 'text'
            assert message_content[0]['text'] == "Test prompt"
            
            for i in range(1, 4):
                assert message_content[i]['type'] == 'image_url'
                assert 'data:image/jpeg;base64,' in message_content[i]['image_url']['url']
    
    def test_analyze_images_with_openrouter_api_error(self, tmp_path):
        """Test API error handling."""
        image_file = tmp_path / "test.jpg"
        image_file.write_bytes(b"fake image")
        
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.ENHANCE_MODEL = "test_model"
        mock_config.IMAGE_ANALYSIS_PROMPT = "Test prompt"
        
        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")
        
        with patch('src.image_analysis.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response), \
             patch('src.image_analysis.encode_image_to_base64', return_value="base64_data"), \
             patch('src.image_analysis.print_flush'), \
             pytest.raises(Exception):
            
            analyze_images_with_openrouter([str(image_file)])
    
    def test_analyze_images_with_openrouter_404_error(self, tmp_path):
        """Test specific 404 error handling."""
        image_file = tmp_path / "test.jpg"
        image_file.write_bytes(b"fake image")
        
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.ENHANCE_MODEL = "invalid_model"
        mock_config.IMAGE_ANALYSIS_PROMPT = "Test prompt"
        
        # Mock 404 response
        import requests
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        
        with patch('src.image_analysis.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response), \
             patch('src.image_analysis.encode_image_to_base64', return_value="base64_data"), \
             patch('src.image_analysis.print_flush') as mock_print:
            
            with pytest.raises(requests.exceptions.HTTPError):
                analyze_images_with_openrouter([str(image_file)])
            
            # Should print specific 404 error message
            mock_print.assert_called()
            error_call = [call for call in mock_print.call_args_list 
                         if "404 Not Found" in str(call)]
            assert len(error_call) > 0
    
    def test_analyze_images_with_openrouter_empty_images(self):
        """Test with empty image list."""
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.ENHANCE_MODEL = "test_model"
        mock_config.IMAGE_ANALYSIS_PROMPT = "Test prompt"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "No images to analyze"}}]
        }
        
        with patch('src.image_analysis.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response) as mock_post:
            
            result = analyze_images_with_openrouter([])
            
            assert result == "No images to analyze"
            
            # Verify request contains only text prompt
            call_args = mock_post.call_args
            request_data = call_args[1]['json']
            message_content = request_data['messages'][0]['content']
            assert len(message_content) == 1  # Only text prompt
            assert message_content[0]['type'] == 'text'
    
    def test_analyze_images_with_openrouter_headers(self, tmp_path):
        """Test that correct headers are sent."""
        image_file = tmp_path / "test.jpg"
        image_file.write_bytes(b"fake image")
        
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.ENHANCE_MODEL = "test_model"
        mock_config.IMAGE_ANALYSIS_PROMPT = "Test prompt"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Analysis result"}}]
        }
        
        with patch('src.image_analysis.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response) as mock_post, \
             patch('src.image_analysis.encode_image_to_base64', return_value="base64_data"):
            
            analyze_images_with_openrouter([str(image_file)])
            
            # Verify headers
            call_args = mock_post.call_args
            headers = call_args[1]['headers']
            
            assert headers['Authorization'] == "Bearer test_api_key"
            assert headers['Content-Type'] == "application/json"
            assert headers['X-Title'] == "Ninadon"
            assert headers['HTTP-Referer'] == "https://github.com/rmoriz/ninadon"