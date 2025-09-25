#!/usr/bin/env python3
import unittest
import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock
import base64

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.web_app import create_web_app, JobManager

class TestWebApp(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.app = create_web_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        
        # Set up basic auth for tests
        os.environ['WEB_USER'] = 'testuser'
        os.environ['WEB_PASSWORD'] = 'testpass'
        
        # Create basic auth header
        credentials = base64.b64encode(b'testuser:testpass').decode('utf-8')
        self.auth_headers = {'Authorization': f'Basic {credentials}'}
        
    def tearDown(self):
        """Clean up after each test."""
        # Clean up environment variables
        if 'WEB_USER' in os.environ:
            del os.environ['WEB_USER']
        if 'WEB_PASSWORD' in os.environ:
            del os.environ['WEB_PASSWORD']

    def test_index_page_without_auth(self):
        """Test that index page requires authentication."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 401)

    def test_index_page_with_auth(self):
        """Test that index page works with authentication."""
        response = self.client.get('/', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Ninadon Video Processor', response.data)

    def test_api_jobs_empty(self):
        """Test API jobs endpoint with no jobs."""
        response = self.client.get('/api/jobs', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data, [])

    @patch('src.web_app.process_video_async')
    def test_api_process_video(self, mock_process):
        """Test API process endpoint."""
        test_data = {
            'url': 'https://www.youtube.com/watch?v=test123',
            'enhance': False,
            'dry_run': True
        }
        
        response = self.client.post('/api/process', 
                                  headers=self.auth_headers,
                                  data=json.dumps(test_data),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('job_id', data)
        self.assertEqual(data['status'], 'created')
        
        # Verify background thread was started
        mock_process.assert_called_once()

    def test_api_process_missing_url(self):
        """Test API process endpoint with missing URL."""
        test_data = {'enhance': False}
        
        response = self.client.post('/api/process',
                                  headers=self.auth_headers,
                                  data=json.dumps(test_data),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)

    def test_api_status_nonexistent_job(self):
        """Test API status endpoint with non-existent job."""
        response = self.client.get('/api/status/nonexistent-job-id', 
                                 headers=self.auth_headers)
        self.assertEqual(response.status_code, 404)

class TestJobManager(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.job_manager = JobManager()

    def test_create_job(self):
        """Test job creation."""
        job_id = self.job_manager.create_job('https://test.com', enhance=True, dry_run=False)
        
        self.assertIsInstance(job_id, str)
        job = self.job_manager.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job['url'], 'https://test.com')
        self.assertEqual(job['enhance'], True)
        self.assertEqual(job['dry_run'], False)
        self.assertEqual(job['status'], 'pending')

    def test_get_nonexistent_job(self):
        """Test getting a job that doesn't exist."""
        job = self.job_manager.get_job('nonexistent')
        self.assertIsNone(job)

    def test_update_job(self):
        """Test updating job status."""
        job_id = self.job_manager.create_job('https://test.com')
        
        self.job_manager.update_job(job_id, status='processing', progress='Downloading...')
        
        job = self.job_manager.get_job(job_id)
        self.assertEqual(job['status'], 'processing')
        self.assertEqual(job['progress'], 'Downloading...')

    def test_list_jobs(self):
        """Test listing all jobs."""
        job_id1 = self.job_manager.create_job('https://test1.com')
        job_id2 = self.job_manager.create_job('https://test2.com')
        
        jobs = self.job_manager.list_jobs()
        self.assertEqual(len(jobs), 2)
        
        job_ids = [job['id'] for job in jobs]
        self.assertIn(job_id1, job_ids)
        self.assertIn(job_id2, job_ids)

class TestWebAppIntegration(unittest.TestCase):
    """Integration tests for the web application."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = create_web_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        
        # Set up auth
        os.environ['WEB_USER'] = 'testuser'
        os.environ['WEB_PASSWORD'] = 'testpass'
        credentials = base64.b64encode(b'testuser:testpass').decode('utf-8')
        self.auth_headers = {'Authorization': f'Basic {credentials}'}

    def tearDown(self):
        """Clean up after each test."""
        if 'WEB_USER' in os.environ:
            del os.environ['WEB_USER']
        if 'WEB_PASSWORD' in os.environ:
            del os.environ['WEB_PASSWORD']

    @patch('src.web_app.process_video_async')
    def test_complete_workflow(self, mock_process):
        """Test a complete workflow from job creation to status check."""
        # Create a job
        test_data = {
            'url': 'https://www.youtube.com/watch?v=test123',
            'enhance': True,
            'dry_run': True
        }
        
        response = self.client.post('/api/process',
                                  headers=self.auth_headers,
                                  data=json.dumps(test_data),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        job_id = data['job_id']
        
        # Check job status
        response = self.client.get(f'/api/jobs/{job_id}', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        job_data = json.loads(response.data)
        
        self.assertEqual(job_data['id'], job_id)
        self.assertEqual(job_data['url'], test_data['url'])
        self.assertEqual(job_data['enhance'], test_data['enhance'])
        self.assertEqual(job_data['dry_run'], test_data['dry_run'])
        
        # Check jobs list
        response = self.client.get('/api/jobs', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        jobs_data = json.loads(response.data)
        
        self.assertEqual(len(jobs_data), 1)
        self.assertEqual(jobs_data[0]['id'], job_id)

if __name__ == '__main__':
    unittest.main()