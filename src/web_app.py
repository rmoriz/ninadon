#!/usr/bin/env python3
"""Web application for video processing interface."""

import tempfile
import threading
import uuid
from datetime import datetime

from flask import Flask, jsonify, request
from flask_httpauth import HTTPBasicAuth

from .ai_services import (
    extract_summary_and_description,
    generate_context_summary,
    summarize_text,
)
from .config import Config
from .database import add_to_database
from .image_analysis import analyze_images_with_openrouter, extract_still_images
from .mastodon_client import post_to_mastodon
from .transcription import extract_transcript_from_platform, transcribe_video
from .utils import print_flush
from .video_downloader import download_video
from .video_processing import maybe_reencode
from . import __version__


class JobManager:
    """Manages background video processing jobs."""

    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def create_job(self, url, enhance=False, dry_run=False):
        job_id = str(uuid.uuid4())
        with self.lock:
            self.jobs[job_id] = {
                "id": job_id,
                "url": url,
                "enhance": enhance,
                "dry_run": dry_run,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "progress": "Job created",
                "result": None,
                "error": None,
            }
        return job_id

    def get_job(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def update_job(self, job_id, **kwargs):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(kwargs)

    def list_jobs(self):
        with self.lock:
            return list(self.jobs.values())


def process_video_async(job_manager, job_id):
    """Process video in background thread."""

    def update_progress(status, progress):
        job_manager.update_job(job_id, status=status, progress=progress)

    try:
        job = job_manager.get_job(job_id)
        if not job:
            return

        url = job["url"]
        enhance = job["enhance"]
        dry_run = job["dry_run"]

        update_progress("processing", "Starting video download...")

        with tempfile.TemporaryDirectory() as tmpdir:
            update_progress("processing", "Downloading video...")
            video_path, title, description, uploader, hashtags, platform, mime_type = (
                download_video(url, tmpdir)
            )

            update_progress("processing", "Extracting transcript...")
            transcript = extract_transcript_from_platform(url, tmpdir)

            if transcript:
                update_progress("processing", "Using platform-provided transcript")
            else:
                update_progress("processing", "Transcribing with Whisper...")
                transcript = transcribe_video(video_path)

            if not transcript or (
                isinstance(transcript, str) and transcript.strip() == ""
            ):
                transcript = "[No audio/transcript available]"

            image_analysis = None
            if enhance:
                update_progress("processing", "Analyzing images...")
                try:
                    image_paths = extract_still_images(video_path, tmpdir)
                    image_analysis = analyze_images_with_openrouter(image_paths)
                except Exception as e:
                    print_flush(f"Warning: Image analysis failed: {e}")

            update_progress("processing", "Adding to database...")
            add_to_database(
                uploader,
                title,
                description,
                hashtags,
                platform,
                transcript,
                image_analysis,
            )

            update_progress("processing", "Generating context summary...")
            context = generate_context_summary(uploader)

            update_progress("processing", "Generating AI summary...")
            ai_response = summarize_text(
                transcript, description, uploader, image_analysis, context
            )
            summary, video_description = extract_summary_and_description(ai_response)

            if Config.ENABLE_TRANSCODING:
                update_progress("processing", "Checking if transcoding needed...")
                final_video_path = maybe_reencode(video_path, tmpdir)
            else:
                final_video_path = video_path

            result = {
                "title": title,
                "uploader": uploader,
                "platform": platform,
                "summary": summary,
                "video_description": video_description,
                "transcript": transcript,
                "hashtags": hashtags,
                "source_url": url,
            }

            if dry_run:
                update_progress("completed", "Dry run completed successfully")
                result["mastodon_url"] = None
                result["dry_run"] = True
            else:
                update_progress("processing", "Posting to Mastodon...")
                mastodon_url = post_to_mastodon(
                    summary, final_video_path, url, mime_type, video_description
                )
                result["mastodon_url"] = mastodon_url
                update_progress("completed", "Posted to Mastodon successfully")

            job_manager.update_job(job_id, status="completed", result=result)

    except Exception as e:
        error_msg = str(e)
        print_flush(f"Job {job_id} failed: {error_msg}")
        job_manager.update_job(
            job_id, status="failed", error=error_msg, progress=f"Failed: {error_msg}"
        )


def create_web_app():
    """Create and configure the Flask web application."""

    app = Flask(__name__)
    auth = HTTPBasicAuth()
    job_manager = JobManager()

    # Basic auth setup
    @auth.verify_password
    def verify_password(username, password):
        config = Config()
        if not config.WEB_USER or not config.WEB_PASSWORD:
            return True  # No auth configured
        return username == config.WEB_USER and password == config.WEB_PASSWORD

    # Simple HTML interface
    HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ninadon Video Processor</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{{{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}}}
            .form-group {{{{ margin-bottom: 15px; }}}}
            label {{{{ display: block; margin-bottom: 5px; font-weight: bold; }}}}
            input[type="url"], button {{{{ padding: 10px; border: 1px solid #ccc; border-radius: 4px; }}}}
            input[type="url"] {{{{ width: 100%; box-sizing: border-box; }}}}
            button {{{{ background: #007cba; color: white; cursor: pointer; margin-right: 10px; }}}}
            button:hover {{{{ background: #005a87; }}}}
            .job {{{{ border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 4px; }}}}
            .status-pending {{{{ border-left: 4px solid #ffa500; }}}}
            .status-processing {{{{ border-left: 4px solid #007cba; }}}}
            .status-completed {{{{ border-left: 4px solid #28a745; }}}}
            .status-failed {{{{ border-left: 4px solid #dc3545; }}}}
            .result {{{{ background: #f8f9fa; padding: 10px; margin-top: 10px; border-radius: 4px; }}}}
        </style>
    </head>
    <body>
        <h1>Ninadon Video Processor</h1>
        <p style="color: #666; font-size: 0.9em;">Version {version}</p>
        <form id="videoForm">
            <div class="form-group">
                <label for="url">Video URL (YouTube, TikTok, Instagram):</label>
                <input type="url" id="url" name="url" required placeholder="https://...">
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="enhance" name="enhance"> Enable image analysis
                </label>
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="dry_run" name="dry_run"> Dry run (don't post to Mastodon)
                </label>
            </div>
            <button type="submit">Process Video</button>
            <button type="button" onclick="refreshJobs()">Refresh Status</button>
        </form>

        <h2>Jobs</h2>
        <div id="jobs"></div>

        <script>
            document.getElementById('videoForm').onsubmit = function(e) {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = {
                    url: formData.get('url'),
                    enhance: formData.get('enhance') === 'on',
                    dry_run: formData.get('dry_run') === 'on'
                };

                fetch('/api/process', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                })
                .then(r => r.json())
                .then(data => {
                    if (data.job_id) {
                        alert('Job created: ' + data.job_id);
                        refreshJobs();
                    } else {
                        alert('Error: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(e => alert('Error: ' + e));
            };

            function refreshJobs() {
                fetch('/api/jobs')
                .then(r => r.json())
                .then(jobs => {
                    const container = document.getElementById('jobs');
                    if (jobs.length === 0) {
                        container.innerHTML = '<p>No jobs yet.</p>';
                        return;
                    }

                    container.innerHTML = jobs.map(job => `
                        <div class="job status-${job.status}">
                            <strong>Job ${job.id.substring(0, 8)}</strong> - ${job.status}
                            <br>URL: ${job.url}
                            <br>Progress: ${job.progress}
                            <br>Created: ${new Date(job.created_at).toLocaleString()}
                            ${job.error ? '<br><strong>Error:</strong> ' + job.error : ''}
                            ${job.result ? '<div class="result"><strong>Result:</strong><br>' +
                                'Title: ' + job.result.title + '<br>' +
                                'Summary: ' + job.result.summary + '<br>' +
                                (job.result.mastodon_url ? 'Mastodon: <a href="' +
                                job.result.mastodon_url + '" target="_blank">' +
                                job.result.mastodon_url + '</a>' : 'Dry run completed') +
                            '</div>' : ''}
                        </div>
                    `).join('');
                });
            }

            // Refresh jobs every 5 seconds
            setInterval(refreshJobs, 5000);
            refreshJobs();
        </script>
    </body>
    </html>
    """

    @app.route("/")
    @auth.login_required
    def index():
        return HTML_TEMPLATE.replace("{version}", __version__)

    @app.route("/api/process", methods=["POST"])
    @auth.login_required
    def api_process():
        try:
            data = request.get_json()
            if not data or "url" not in data:
                return jsonify({"error": "URL is required"}), 400

            url = data["url"]
            enhance = data.get("enhance", False)
            dry_run = data.get("dry_run", False)

            job_id = job_manager.create_job(url, enhance, dry_run)

            # Start processing in background thread
            thread = threading.Thread(
                target=process_video_async, args=(job_manager, job_id)
            )
            thread.daemon = True
            thread.start()

            return jsonify({"job_id": job_id, "status": "created"})

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs", methods=["GET"])
    @auth.login_required
    def api_jobs():
        jobs = job_manager.list_jobs()
        # Sort by creation time, newest first
        jobs.sort(key=lambda x: x["created_at"], reverse=True)
        return jsonify(jobs)

    @app.route("/api/jobs/<job_id>", methods=["GET"])
    @auth.login_required
    def api_job_status(job_id):
        job = job_manager.get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(job)

    return app
