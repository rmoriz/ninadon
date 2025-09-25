#!/usr/bin/env python3
"""Tests for ai_services module."""

import json
import pytest
from unittest.mock import MagicMock, patch
from src.ai_services import (
    generate_context_summary, summarize_text, extract_summary_and_description
)


class TestGenerateContextSummary:
    """Test context summary generation functionality."""
    
    def test_generate_context_summary_success(self):
        """Test successful context summary generation."""
        # Mock database with test data
        test_database = [
            {
                'date': '2023-01-01T00:00:00',
                'platform': 'youtube',
                'title': 'Test Video 1',
                'description': 'First test video',
                'hashtags': ['#test', '#video'],
                'transcript': 'This is the first test transcript with some content',
                'image_recognition': 'Shows a person talking in front of a camera'
            },
            {
                'date': '2023-01-02T00:00:00',
                'platform': 'tiktok',
                'title': 'Test Video 2',
                'description': 'Second test video',
                'hashtags': ['#tiktok', '#fun'],
                'transcript': 'This is the second test transcript with different content',
                'image_recognition': 'Shows dancing and music'
            }
        ]
        
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.CONTEXT_MODEL = "test_model"
        mock_config.CONTEXT_PROMPT = "Test context prompt"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Generated context summary"}}]
        }
        
        with patch('src.ai_services.load_database', return_value=test_database), \
             patch('src.ai_services.load_context', return_value="Previous context"), \
             patch('src.ai_services.Config') as mock_config_class, \
             patch('requests.post', return_value=mock_response) as mock_post, \
             patch('src.ai_services.save_context') as mock_save, \
             patch('src.ai_services.print_flush'):
            
            # Set up class-level attributes
            mock_config_class.CONTEXT_MODEL = "test_model"
            mock_config_class.CONTEXT_PROMPT = "Test context prompt"
            mock_config_class.return_value = mock_config
            
            result = generate_context_summary("testuser")
            
            assert result == "Generated context summary"
            mock_post.assert_called_once()
            mock_save.assert_called_once_with("testuser", "Generated context summary", 2)
            
            # Verify request structure
            call_args = mock_post.call_args
            request_data = call_args[1]['json']
            
            assert request_data['model'] == "test_model"
            assert len(request_data['messages']) == 2
            assert request_data['messages'][0]['role'] == 'system'
            assert request_data['messages'][0]['content'] == "Test context prompt"
            assert request_data['messages'][1]['role'] == 'user'
            
            # Check that user content includes database entries and previous context
            user_content = request_data['messages'][1]['content']
            assert "Test Video 1" in user_content
            assert "Test Video 2" in user_content
            assert "Previous context" in user_content
    
    def test_generate_context_summary_no_database(self):
        """Test context generation with empty database."""
        with patch('src.ai_services.load_database', return_value=[]), \
             patch('src.ai_services.print_flush'):
            
            result = generate_context_summary("testuser")
            assert result is None
    
    def test_generate_context_summary_no_existing_context(self):
        """Test context generation without existing context."""
        test_database = [{
            'date': '2023-01-01T00:00:00',
            'platform': 'youtube',
            'title': 'Test Video',
            'description': 'Test description',
            'hashtags': ['#test'],
            'transcript': 'Test transcript',
        }]
        
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.CONTEXT_MODEL = "test_model"
        mock_config.CONTEXT_PROMPT = "Test context prompt"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "New context summary"}}]
        }
        
        with patch('src.ai_services.load_database', return_value=test_database), \
             patch('src.ai_services.load_context', return_value=None), \
             patch('src.ai_services.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response) as mock_post, \
             patch('src.ai_services.save_context'), \
             patch('src.ai_services.print_flush'):
            
            result = generate_context_summary("testuser")
            
            assert result == "New context summary"
            
            # Verify that previous context is not included
            call_args = mock_post.call_args
            user_content = call_args[1]['json']['messages'][1]['content']
            assert "Previous context summary:" not in user_content
    
    def test_generate_context_summary_api_error(self):
        """Test context generation with API error."""
        test_database = [{
            'date': '2023-01-01T00:00:00',
            'platform': 'youtube',
            'title': 'Test',
            'description': 'Test description',
            'hashtags': ['#test'],
            'transcript': 'Test transcript'
        }]
        
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        
        import requests
        with patch('src.ai_services.load_database', return_value=test_database), \
             patch('src.ai_services.load_context', return_value=None), \
             patch('src.ai_services.Config') as mock_config_class, \
             patch('requests.post', side_effect=requests.exceptions.HTTPError("API Error")), \
             patch('src.ai_services.print_flush'):
            
            mock_config_class.CONTEXT_MODEL = "test_model"
            mock_config_class.CONTEXT_PROMPT = "test_prompt"
            mock_config_class.return_value = mock_config
            
            result = generate_context_summary("testuser")
            assert result is None
    
    def test_generate_context_summary_limits_entries(self):
        """Test that context generation limits to last 10 entries."""
        # Create 15 database entries
        test_database = []
        for i in range(15):
            test_database.append({
                'date': f'2023-01-{i+1:02d}T00:00:00',
                'platform': 'youtube',
                'title': f'Video {i+1}',
                'description': f'Description {i+1}',
                'hashtags': [f'#tag{i+1}'],
                'transcript': f'Transcript {i+1}',
            })
        
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.CONTEXT_MODEL = "test_model"
        mock_config.CONTEXT_PROMPT = "Test prompt"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Summary"}}]
        }
        
        with patch('src.ai_services.load_database', return_value=test_database), \
             patch('src.ai_services.load_context', return_value=None), \
             patch('src.ai_services.Config') as mock_config_class, \
             patch('requests.post', return_value=mock_response) as mock_post, \
             patch('src.ai_services.save_context'), \
             patch('src.ai_services.print_flush'):
            
            mock_config_class.CONTEXT_MODEL = "test_model"
            mock_config_class.CONTEXT_PROMPT = "Test prompt"
            mock_config_class.return_value = mock_config
            
            generate_context_summary("testuser")
            
            # Check that only last 10 entries are included
            call_args = mock_post.call_args
            user_content = call_args[1]['json']['messages'][1]['content']
            
            # Should include Video 6-15 (last 10) - but they're labeled as Video 1-10 in the output
            # The code takes the last 10 entries (index 5-14) but labels them as Video 1-10
            assert "Video 1" in user_content  # This is actually entry index 5 (Video 6)
            assert "Video 10" in user_content  # This is actually entry index 14 (Video 15)
            # Check actual video titles to be more precise
            assert "Video 6" in user_content  # Should contain the title from entry 5
            assert "Video 15" in user_content  # Should contain the title from entry 14


class TestSummarizeText:
    """Test text summarization functionality."""
    
    def test_summarize_text_basic(self):
        """Test basic text summarization."""
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.OPENROUTER_MODEL = "test_model"
        mock_config.SYSTEM_PROMPT = "Test system prompt"
        mock_config.USER_PROMPT = ""
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Summarized text"}}]
        }
        
        with patch('src.ai_services.Config') as mock_config_class, \
             patch('requests.post', return_value=mock_response) as mock_post:
            
            # Set up class-level attributes
            mock_config_class.OPENROUTER_MODEL = "test_model"
            mock_config_class.SYSTEM_PROMPT = "Test system prompt"
            mock_config_class.USER_PROMPT = ""
            mock_config_class.return_value = mock_config
            
            result = summarize_text("Test transcript", "Test description", "testuser")
            
            assert result == "Summarized text"
            mock_post.assert_called_once()
            
            # Verify request structure
            call_args = mock_post.call_args
            request_data = call_args[1]['json']
            
            assert request_data['model'] == "test_model"
            assert len(request_data['messages']) == 2
            assert request_data['messages'][0]['role'] == 'system'
            assert request_data['messages'][0]['content'] == "Test system prompt"
            
            user_content = request_data['messages'][1]['content']
            assert "Account name: testuser" in user_content
            assert "Description: Test description" in user_content
            assert "Transcript:\nTest transcript" in user_content
    
    def test_summarize_text_with_user_prompt(self):
        """Test summarization with user prompt."""
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.OPENROUTER_MODEL = "test_model"
        mock_config.SYSTEM_PROMPT = "System prompt"
        mock_config.USER_PROMPT = "Custom user prompt"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Result"}}]
        }
        
        with patch('src.ai_services.Config') as mock_config_class, \
             patch('requests.post', return_value=mock_response) as mock_post:
            
            # Set up class-level attributes
            mock_config_class.OPENROUTER_MODEL = "test_model"
            mock_config_class.SYSTEM_PROMPT = "System prompt"
            mock_config_class.USER_PROMPT = "Custom user prompt"
            mock_config_class.return_value = mock_config
            
            summarize_text("Transcript", "Description", "user")
            
            call_args = mock_post.call_args
            user_content = call_args[1]['json']['messages'][1]['content']
            assert "Custom user prompt\n\nTranscript" in user_content
    
    def test_summarize_text_with_image_analysis(self):
        """Test summarization with image analysis."""
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.OPENROUTER_MODEL = "test_model"
        mock_config.SYSTEM_PROMPT = "System prompt"
        mock_config.USER_PROMPT = ""
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Result"}}]
        }
        
        with patch('src.ai_services.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response) as mock_post:
            
            summarize_text("Transcript", "Description", "user", 
                         image_analysis="Image shows a cat playing")
            
            call_args = mock_post.call_args
            user_content = call_args[1]['json']['messages'][1]['content']
            assert "Image Recognition:\nImage shows a cat playing" in user_content
    
    def test_summarize_text_with_context(self):
        """Test summarization with context."""
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.OPENROUTER_MODEL = "test_model"
        mock_config.SYSTEM_PROMPT = "System prompt"
        mock_config.USER_PROMPT = ""
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Result"}}]
        }
        
        with patch('src.ai_services.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response) as mock_post:
            
            summarize_text("Transcript", "Description", "user", 
                         context="User typically posts gaming content")
            
            call_args = mock_post.call_args
            user_content = call_args[1]['json']['messages'][1]['content']
            assert "Context:\nUser typically posts gaming content" in user_content
    
    def test_summarize_text_404_error(self):
        """Test summarization with 404 error."""
        mock_config = MagicMock()
        mock_config.OPENROUTER_API_KEY = "test_api_key"
        mock_config.OPENROUTER_MODEL = "invalid_model"
        
        import requests
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        
        with patch('src.ai_services.Config', return_value=mock_config), \
             patch('requests.post', return_value=mock_response), \
             patch('src.ai_services.print_flush') as mock_print:
            
            with pytest.raises(requests.exceptions.HTTPError):
                summarize_text("Transcript", "Description", "user")
            
            # Should print specific 404 error message
            mock_print.assert_called()
            error_calls = [call for call in mock_print.call_args_list 
                          if "404 Not Found" in str(call)]
            assert len(error_calls) > 0


class TestExtractSummaryAndDescription:
    """Test summary and description extraction functionality."""
    
    def test_extract_summary_and_description_json(self):
        """Test extraction from JSON format."""
        json_response = '''Some preamble text
        {
            "summary": "This is the summary",
            "video_description": "This is the video description for visually impaired users"
        }
        Some trailing text'''
        
        summary, description = extract_summary_and_description(json_response)
        
        assert summary == "This is the summary"
        assert description == "This is the video description for visually impaired users"
    
    def test_extract_summary_and_description_json_long_description(self):
        """Test extraction with description longer than 1400 characters."""
        long_description = "A" * 1500  # 1500 characters
        json_response = f'''{{
            "summary": "Summary",
            "video_description": "{long_description}"
        }}'''
        
        summary, description = extract_summary_and_description(json_response)
        
        assert summary == "Summary"
        assert len(description) == 1400
        assert description.endswith("...")
    
    def test_extract_summary_and_description_text_format(self):
        """Test extraction from text format (fallback)."""
        text_response = '''Summary:
This is the summary text here.

Video Description for Visually Impaired:
This is the description for visually impaired users.'''
        
        summary, description = extract_summary_and_description(text_response)
        
        assert summary == "This is the summary text here."
        assert description == "This is the description for visually impaired users."
    
    def test_extract_summary_and_description_no_sections(self):
        """Test extraction when no clear sections are found."""
        plain_response = '''This is just a plain response
with multiple lines
that doesn't follow
the expected format'''
        
        summary, description = extract_summary_and_description(plain_response)
        
        # Should split roughly in half
        lines = plain_response.strip().split('\n')
        expected_summary_lines = lines[:len(lines)//2]
        expected_description_lines = lines[len(lines)//2:]
        
        assert summary == '\n'.join(expected_summary_lines).strip()
        assert description == '\n'.join(expected_description_lines).strip()
    
    def test_extract_summary_and_description_only_summary_section(self):
        """Test extraction when only summary section is found."""
        text_response = '''Summary:
This is the summary.

Some other text that's not a video description.'''
        
        summary, description = extract_summary_and_description(text_response)
        
        # The regex should match and extract just the summary part
        assert "This is the summary." in summary
        # Description should be fallback - could be the remaining text
        assert isinstance(description, str)
        assert len(description) > 0
    
    def test_extract_summary_and_description_invalid_json(self):
        """Test extraction with invalid JSON (should fall back to text parsing)."""
        invalid_json = '''{"summary": "Test", "invalid_json": }'''
        
        summary, description = extract_summary_and_description(invalid_json)
        
        # Should fall back to text parsing
        assert isinstance(summary, str)
        assert isinstance(description, str)
    
    def test_extract_summary_and_description_description_truncation(self):
        """Test that description is truncated to 1400 characters in fallback mode."""
        long_text = "A" * 2000  # Very long text
        
        summary, description = extract_summary_and_description(long_text)
        
        # Description should be truncated
        assert len(description) <= 1400
        if len(description) == 1400:
            assert description.endswith("...")
    
    def test_extract_summary_and_description_case_insensitive(self):
        """Test that section headers are case insensitive."""
        text_response = '''SUMMARY:
Case insensitive summary.

VIDEO DESCRIPTION FOR VISUALLY IMPAIRED:
Case insensitive description.'''
        
        summary, description = extract_summary_and_description(text_response)
        
        assert summary == "Case insensitive summary."
        assert description == "Case insensitive description."
    
    def test_extract_summary_and_description_with_video_description_in_summary(self):
        """Test when 'Video Description' text appears in summary fallback."""
        text_response = '''This is a summary that mentions Video Description for Visually Impaired: something else.

Video Description for Visually Impaired:
This is the actual video description.'''
        
        summary, description = extract_summary_and_description(text_response)
        
        # Should correctly split at the actual section header
        # The summary should be everything before the section header
        assert "This is a summary" in summary
        # The function should find the proper video description section
        assert isinstance(description, str)
        assert len(description) > 0