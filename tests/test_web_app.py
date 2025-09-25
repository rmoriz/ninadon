#!/usr/bin/env python3
"""Tests for web_app module."""

import json
import pytest
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch
from src.web_app import JobManager, process_video_async, create_web_app


class TestJobManager:
    """Test job management functionality."""
    
    def test_create_job(self):
        """Test job creation."""
        manager = JobManager()
        
        with patch('src.web_app.datetime') as mock_datetime:
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
            
            job_id = manager.create_job("https://example.com/video", enhance=True, dry_run=False)
            
            assert isinstance(job_id, str)
            assert len(job_id) == 36  # UUID4 length
            
            job = manager.get_job(job_id)
            assert job['id'] == job_id
            assert job['url'] == "https://example.com/video"
            assert job['enhance'] is True
            assert job['dry_run'] is False
            assert job['status'] == 'pending'
            assert job['created_at'] == "2023-01-01T00:00:00"
            assert job['progress'] == 'Job created'
            assert job['result'] is None
            assert job['error'] is None
    
    def test_get_job_exists(self):
        """Test getting existing job."""
        manager = JobManager()
        job_id = manager.create_job("https://example.com/video")
        
        job = manager.get_job(job_id)
        assert job is not None
        assert job['id'] == job_id
    
    def test_get_job_not_exists(self):
        """Test getting non-existent job."""
        manager = JobManager()
        
        job = manager.get_job("nonexistent-id")
        assert job is None
    
    def test_update_job(self):
        """Test job updates."""
        manager = JobManager()
        job_id = manager.create_job("https://example.com/video")
        
        manager.update_job(job_id, status='processing', progress='Downloading video...')
        
        job = manager.get_job(job_id)
        assert job['status'] == 'processing'
        assert job['progress'] == 'Downloading video...'
        assert job['url'] == "https://example.com/video"  # Other fields unchanged
    
    def test_update_nonexistent_job(self):
        """Test updating non-existent job."""
        manager = JobManager()
        
        # Should not raise an error
        manager.update_job("nonexistent-id", status='failed')
        
        job = manager.get_job("nonexistent-id")
        assert job is None
    
    def test_list_jobs(self):
        """Test listing all jobs."""
        manager = JobManager()
        
        # Initially empty
        jobs = manager.list_jobs()
        assert jobs == []
        
        # Add some jobs
        job_id1 = manager.create_job("https://example.com/video1")
        job_id2 = manager.create_job("https://example.com/video2", enhance=True)
        
        jobs = manager.list_jobs()
        assert len(jobs) == 2
        
        job_ids = [job['id'] for job in jobs]
        assert job_id1 in job_ids
        assert job_id2 in job_ids
    
    def test_thread_safety(self):
        """Test thread safety of JobManager."""
        manager = JobManager()
        job_ids = []
        
        def create_jobs():
            for i in range(10):
                job_id = manager.create_job(f"https://example.com/video{i}")
                job_ids.append(job_id)
        
        # Create jobs from multiple threads
        threads = [threading.Thread(target=create_jobs) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # Should have 30 jobs total (3 threads × 10 jobs each)
        jobs = manager.list_jobs()
        assert len(jobs) == 30
        
        # All job IDs should be unique
        all_job_ids = [job['id'] for job in jobs]
        assert len(set(all_job_ids)) == 30


class TestProcessVideoAsync:
    """Test asynchronous video processing functionality."""
    
    def test_process_video_async_success(self):
        """Test successful video processing."""
        manager = JobManager()
        job_id = manager.create_job("https://example.com/video", enhance=True, dry_run=True)
        
        # Mock all the processing functions
        with patch('src.web_app.download_video') as mock_download, \
             patch('src.web_app.extract_transcript_from_platform') as mock_transcript, \
             patch('src.web_app.transcribe_video') as mock_whisper, \
             patch('src.web_app.extract_still_images') as mock_images, \
             patch('src.web_app.analyze_images_with_openrouter') as mock_analyze, \
             patch('src.web_app.add_to_database') as mock_db, \
             patch('src.web_app.generate_context_summary') as mock_context, \
             patch('src.web_app.summarize_text') as mock_summarize, \
             patch('src.web_app.extract_summary_and_description') as mock_extract, \
             patch('src.web_app.tempfile.TemporaryDirectory') as mock_tmpdir, \
             patch('src.web_app.Config') as mock_config:
            
            # Setup mocks
            mock_tmpdir.return_value.__enter__.return_value = "/tmp/test"
            mock_download.return_value = (
                "/tmp/test/video.mp4", "Test Video", "Test Description", 
                "testuser", ["#test"], "youtube", "video/mp4"
            )
            mock_transcript.return_value = "Platform transcript"
            mock_images.return_value = ["/tmp/test/frame1.jpg", "/tmp/test/frame2.jpg"]
            mock_analyze.return_value = "Image analysis result"
            mock_context.return_value = "Context summary"
            mock_summarize.return_value = "AI response"
            mock_extract.return_value = ("Summary", "Video description")
            mock_config.ENABLE_TRANSCODING = False
            
            # Run the async processing
            process_video_async(manager, job_id)
            
            # Verify job completed successfully
            job = manager.get_job(job_id)
            assert job['status'] == 'completed'
            assert job['result'] is not None
            
            result = job['result']
            assert result['title'] == "Test Video"
            assert result['uploader'] == "testuser"
            assert result['platform'] == "youtube"
            assert result['summary'] == "Summary"
            assert result['video_description'] == "Video description"
            assert result['dry_run'] is True
            assert result['mastodon_url'] is None
    
    def test_process_video_async_with_posting(self):
        """Test video processing with Mastodon posting."""
        manager = JobManager()
        job_id = manager.create_job("https://example.com/video", dry_run=False)
        
        with patch('src.web_app.download_video') as mock_download, \
             patch('src.web_app.extract_transcript_from_platform', return_value=None), \
             patch('src.web_app.transcribe_video', return_value="Whisper transcript"), \
             patch('src.web_app.add_to_database'), \
             patch('src.web_app.generate_context_summary', return_value="Context"), \
             patch('src.web_app.summarize_text', return_value="AI response"), \
             patch('src.web_app.extract_summary_and_description', return_value=("Summary", "Description")), \
             patch('src.web_app.post_to_mastodon', return_value="https://mastodon.example.com/status/123"), \
             patch('src.web_app.tempfile.TemporaryDirectory') as mock_tmpdir, \
             patch('src.web_app.Config') as mock_config:
            
            mock_tmpdir.return_value.__enter__.return_value = "/tmp/test"
            mock_download.return_value = (
                "/tmp/test/video.mp4", "Test Video", "Description", 
                "testuser", ["#test"], "youtube", "video/mp4"
            )
            mock_config.ENABLE_TRANSCODING = False
            
            process_video_async(manager, job_id)
            
            job = manager.get_job(job_id)
            assert job['status'] == 'completed'
            assert job['result']['mastodon_url'] == "https://mastodon.example.com/status/123"
            assert 'dry_run' not in job['result'] or job['result']['dry_run'] is False
    
    def test_process_video_async_error_handling(self):
        """Test error handling in video processing."""
        manager = JobManager()
        job_id = manager.create_job("https://example.com/video")
        
        with patch('src.web_app.download_video', side_effect=Exception("Download failed")), \
             patch('src.web_app.tempfile.TemporaryDirectory') as mock_tmpdir, \
             patch('src.web_app.print_flush'):
            
            mock_tmpdir.return_value.__enter__.return_value = "/tmp/test"
            
            process_video_async(manager, job_id)
            
            job = manager.get_job(job_id)
            assert job['status'] == 'failed'
            assert job['error'] == "Download failed"
            assert "Failed: Download failed" in job['progress']
    
    def test_process_video_async_no_transcript(self):
        """Test processing when no transcript is available."""
        manager = JobManager()
        job_id = manager.create_job("https://example.com/video", dry_run=True)
        
        with patch('src.web_app.download_video') as mock_download, \
             patch('src.web_app.extract_transcript_from_platform', return_value=None), \
             patch('src.web_app.transcribe_video', return_value=""), \
             patch('src.web_app.add_to_database'), \
             patch('src.web_app.generate_context_summary', return_value=None), \
             patch('src.web_app.summarize_text', return_value="AI response"), \
             patch('src.web_app.extract_summary_and_description', return_value=("Summary", "Description")), \
             patch('src.web_app.tempfile.TemporaryDirectory') as mock_tmpdir, \
             patch('src.web_app.Config') as mock_config:
            
            mock_tmpdir.return_value.__enter__.return_value = "/tmp/test"
            mock_download.return_value = (
                "/tmp/test/video.mp4", "Test Video", "Description", 
                "testuser", ["#test"], "youtube", "video/mp4"
            )
            mock_config.ENABLE_TRANSCODING = False
            
            process_video_async(manager, job_id)
            
            job = manager.get_job(job_id)
            assert job['status'] == 'completed'
            assert job['result']['transcript'] == "[No audio/transcript available]"
    
    def test_process_video_async_image_analysis_error(self):
        """Test processing when image analysis fails."""
        manager = JobManager()
        job_id = manager.create_job("https://example.com/video", enhance=True, dry_run=True)
        
        with patch('src.web_app.download_video') as mock_download, \
             patch('src.web_app.extract_transcript_from_platform', return_value="Transcript"), \
             patch('src.web_app.extract_still_images', side_effect=Exception("Image extraction failed")), \
             patch('src.web_app.add_to_database'), \
             patch('src.web_app.generate_context_summary', return_value=None), \
             patch('src.web_app.summarize_text', return_value="AI response"), \
             patch('src.web_app.extract_summary_and_description', return_value=("Summary", "Description")), \
             patch('src.web_app.tempfile.TemporaryDirectory') as mock_tmpdir, \
             patch('src.web_app.Config') as mock_config, \
             patch('src.web_app.print_flush'):
            
            mock_tmpdir.return_value.__enter__.return_value = "/tmp/test"
            mock_download.return_value = (
                "/tmp/test/video.mp4", "Test Video", "Description", 
                "testuser", ["#test"], "youtube", "video/mp4"
            )
            mock_config.ENABLE_TRANSCODING = False
            
            process_video_async(manager, job_id)
            
            # Should complete successfully despite image analysis failure
            job = manager.get_job(job_id)
            assert job['status'] == 'completed'


class TestCreateWebApp:
    """Test web application creation and endpoints."""
    
    def test_create_web_app(self):
        """Test web app creation."""
        app = create_web_app()
        assert app is not None
        assert app.name == 'src.web_app'
    
    def test_index_route_no_auth(self):
        """Test index route without authentication."""
        with patch('src.web_app.Config') as mock_config:
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            response = client.get('/')
            assert response.status_code == 200
            assert b'Ninadon Video Processor' in response.data
    
    def test_index_route_with_auth_no_credentials(self):
        """Test index route with auth but no credentials provided."""
        with patch('src.web_app.Config') as mock_config:
            mock_config.WEB_USER = "testuser"
            mock_config.WEB_PASSWORD = "testpass"
            
            app = create_web_app()
            client = app.test_client()
            
            response = client.get('/')
            assert response.status_code == 401
    
    def test_index_route_with_auth_valid_credentials(self):
        """Test index route with valid credentials."""
        with patch('src.web_app.Config') as mock_config:
            mock_config.WEB_USER = "testuser"
            mock_config.WEB_PASSWORD = "testpass"
            
            app = create_web_app()
            client = app.test_client()
            
            import base64
            credentials = base64.b64encode(b'testuser:testpass').decode('utf-8')
            headers = {'Authorization': f'Basic {credentials}'}
            
            response = client.get('/', headers=headers)
            assert response.status_code == 200
            assert b'Ninadon Video Processor' in response.data
    
    def test_api_process_missing_url(self):
        """Test API process endpoint with missing URL."""
        with patch('src.web_app.Config') as mock_config:
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            response = client.post('/api/process', 
                                 data=json.dumps({}), 
                                 content_type='application/json')
            
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'error' in data
            assert 'URL is required' in data['error']
    
    def test_api_process_success(self):
        """Test successful API process request."""
        with patch('src.web_app.Config') as mock_config, \
             patch('threading.Thread') as mock_thread:
            
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            request_data = {
                'url': 'https://example.com/video',
                'enhance': True,
                'dry_run': False
            }
            
            response = client.post('/api/process',
                                 data=json.dumps(request_data),
                                 content_type='application/json')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'job_id' in data
            assert isinstance(data['job_id'], str)
            
            # Verify thread was started
            mock_thread.assert_called_once()
            mock_thread.return_value.start.assert_called_once()
    
    def test_api_jobs_empty(self):
        """Test API jobs endpoint with no jobs."""
        with patch('src.web_app.Config') as mock_config:
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            response = client.get('/api/jobs')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data == []
    
    def test_api_jobs_with_jobs(self):
        """Test API jobs endpoint with existing jobs."""
        with patch('src.web_app.Config') as mock_config, \
             patch('threading.Thread'):
            
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            # Create a job first
            request_data = {'url': 'https://example.com/video'}
            client.post('/api/process',
                       data=json.dumps(request_data),
                       content_type='application/json')
            
            # Get jobs
            response = client.get('/api/jobs')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert len(data) == 1
            assert data[0]['url'] == 'https://example.com/video'
            assert data[0]['status'] == 'pending'
    
    def test_api_job_status_exists(self):
        """Test API job status endpoint for existing job."""
        with patch('src.web_app.Config') as mock_config, \
             patch('threading.Thread'):
            
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            # Create a job
            request_data = {'url': 'https://example.com/video'}
            response = client.post('/api/process',
                                 data=json.dumps(request_data),
                                 content_type='application/json')
            
            job_id = json.loads(response.data)['job_id']
            
            # Get job status
            response = client.get(f'/api/jobs/{job_id}')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data['id'] == job_id
            assert data['url'] == 'https://example.com/video'
    
    def test_api_job_status_not_found(self):
        """Test API job status endpoint for non-existent job."""
        with patch('src.web_app.Config') as mock_config:
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            response = client.get('/api/jobs/nonexistent-job-id')
            assert response.status_code == 404
            
            data = json.loads(response.data)
            assert 'error' in data
            assert 'Job not found' in data['error']
    
    def test_html_template_content(self):
        """Test that HTML template contains expected content."""
        with patch('src.web_app.Config') as mock_config:
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            response = client.get('/')
            html_content = response.data.decode('utf-8')
            
            # Check for key elements
            assert 'Ninadon Video Processor' in html_content
            assert 'Video URL (YouTube, TikTok, Instagram)' in html_content
            assert 'Enable image analysis' in html_content
            assert 'Dry run (don\'t post to Mastodon)' in html_content
            assert 'Process Video' in html_content
            assert 'Refresh Status' in html_content
    
    def test_api_process_exception_handling(self):
        """Test API process endpoint exception handling."""
        with patch('src.web_app.Config') as mock_config:
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            app = create_web_app()
            client = app.test_client()
            
            # Send invalid JSON
            response = client.post('/api/process',
                                 data='invalid json',
                                 content_type='application/json')
            
            assert response.status_code == 500
            data = json.loads(response.data)
            assert 'error' in data


class TestWebAppIntegration:
    """Test web application integration scenarios."""
    
    def test_complete_job_workflow(self):
        """Test complete job workflow through web interface."""
        with patch('src.web_app.Config') as mock_config, \
             patch('src.web_app.process_video_async') as mock_process:
            
            mock_config.WEB_USER = None
            mock_config.WEB_PASSWORD = None
            
            def mock_process_func(manager, job_id):
                # Simulate successful processing
                manager.update_job(job_id, 
                    status='completed',
                    result={
                        'title': 'Test Video',
                        'summary': 'Test summary',
                        'mastodon_url': 'https://mastodon.example.com/status/123'
                    }
                )
            
            mock_process.side_effect = mock_process_func
            
            app = create_web_app()
            client = app.test_client()
            
            # Create job
            request_data = {'url': 'https://example.com/video', 'dry_run': False}
            response = client.post('/api/process',
                                 data=json.dumps(request_data),
                                 content_type='application/json')
            
            job_id = json.loads(response.data)['job_id']
            
            # Simulate processing completion
            time.sleep(0.1)  # Brief delay to ensure async processing
            
            # Check job status
            response = client.get(f'/api/jobs/{job_id}')
            data = json.loads(response.data)
            
            assert data['status'] == 'completed'
            assert data['result']['title'] == 'Test Video'
            assert data['result']['mastodon_url'] == 'https://mastodon.example.com/status/123'