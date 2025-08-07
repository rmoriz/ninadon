<div align="center">
  <img src="docs/logo.png" alt="ninadon logo" width="288" />
</div>

# ninadon

Automate the workflow of downloading a video (YouTube, Instagram, TikTok), transcribing it with OpenAI Whisper, summarizing with OpenRouter AI, optionally re-encoding to H.265, and posting the summary and video to Mastodon.

---

**Official Docker image for amd64 and arm64 is available at:**

```
 ghcr.io/rmoriz/ninadon
```

---

## Features

- Download videos from YouTube, Instagram, TikTok (via yt-dlp)
- Transcribe audio using OpenAI Whisper
- Summarize transcript with OpenRouter AI
- Optionally re-encode videos >25MB to H.265 (ffmpeg)
- Post summary and video to Mastodon
- Cleans up temporary files automatically
- Dockerized for easy deployment
- **Modular, maintainable codebase:**
  - Repeated logic is extracted into helper functions for clarity and reuse
  - Logging is standardized with `print_flush` for consistent output
  - Environment variable access is robust and centralized

## Installation

### 1. Docker (Recommended)

You can use the prebuilt multi-arch image (amd64, arm64) from GitHub Container Registry:

```sh
docker pull ghcr.io/rmoriz/ninadon:latest
```

Or build the Docker image yourself:

```sh
docker build -t ninadon .
```

### 2. Manual (Python)

Install dependencies:

```sh
pip install -r requirements.txt
```

## Environment Variables

Set these variables before running:

- `OPENROUTER_API_KEY` — API key for OpenRouter (AI summarization)
- `AUTH_TOKEN` — Mastodon access token
- `MASTODON_URL` — Mastodon instance URL (default: `https://mastodon.social`)
- `SYSTEM_PROMPT` — (optional) Custom prompt for summarization
- `USER_PROMPT` — (optional) Custom user prompt to prepend to the transcript before summarization. If set, its contents will be merged with the transcribed text and sent to OpenRouter for summarization.
- `OPENROUTER_MODEL` — (optional) Model name for OpenRouter summarization. Defaults to `openrouter/horizon-beta`.  
  Example: `OPENROUTER_MODEL=tngtech/deepseek-r1t2-chimera:free`
- `ENABLE_TRANSCODING` — (optional) If set to `1`, `true`, or `yes` (case-insensitive), enables video transcoding to H.265 for files >25MB. Default: transcoding is disabled and the original video is used.
- `TRANSCODE_TIMEOUT` — (optional) Timeout in seconds for ffmpeg transcoding. Default: `600`.
- `MASTODON_MEDIA_TIMEOUT` — (optional) Timeout in seconds to wait for Mastodon to process uploaded media. Default: `600`.

## Usage

### CLI

```sh
python src/main.py "https://www.youtube.com/watch?v=example"
```

#### Dry Run

To test the workflow without actually posting to Mastodon, use the `--dry` flag:

```sh
python src/main.py --dry "https://www.youtube.com/watch?v=example"
```

This will download, transcribe, and summarize the video, but skip the actual Mastodon post.

### Docker

Using the prebuilt image:

```sh
docker run --rm \
  -e OPENROUTER_API_KEY=your_openrouter_key \
  -e AUTH_TOKEN=your_mastodon_token \
  -e MASTODON_URL=https://mastodon.social \
  ghcr.io/rmoriz/ninadon:latest "https://www.youtube.com/watch?v=example"
```

Or with your own build:

```sh
docker run --rm \
  -e OPENROUTER_API_KEY=your_openrouter_key \
  -e AUTH_TOKEN=your_mastodon_token \
  -e MASTODON_URL=https://mastodon.social \
  ninadon "https://www.youtube.com/watch?v=example"
```

#### Docker Dry Run

For dry run with Docker (note: AUTH_TOKEN and MASTODON_URL are not required for dry runs):

```sh
docker run --rm \
  -e OPENROUTER_API_KEY=your_openrouter_key \
  ghcr.io/rmoriz/ninadon:latest --dry "https://www.youtube.com/watch?v=example"
```

## Example Output

### Example Mastodon Post

![Example Mastodon Post](docs/example-mastodon-post.png)

### Normal Run Output

```
Working in temp dir: /tmp/tmpabcd1234
Downloaded video to: /tmp/tmpabcd1234/video.mp4
Transcript:
  Pizza-Schiffchen, Puhl, alles wunderbar, wunderschönes Wett
Summary:
  A short summary of the video content...
Final video for posting: /tmp/tmpabcd1234/video_h265.mp4
Uploading video to Mastodon...
Waiting for Mastodon to process video...
Posting status to Mastodon...
Posted to Mastodon: https://mastodon.social/@youruser/123456
```

### Dry Run Output

```
Working in temp dir: /tmp/tmpabcd1234
Downloaded video to: /tmp/tmpabcd1234/video.mp4
Transcript:
  Pizza-Schiffchen, Puhl, alles wunderbar, wunderschönes Wett
Summary:
  A short summary of the video content...
Final video for posting: /tmp/tmpabcd1234/video_h265.mp4
DRY RUN: Skipping Mastodon post
Would post summary:
  A short summary of the video content...
Would post video: /tmp/tmpabcd1234/video_h265.mp4
Would include source URL: https://www.youtube.com/watch?v=example
```

## Troubleshooting

- **Mastodon API Error 422:** The app now waits for Mastodon to finish processing the video before posting. If you still see this error, check your Mastodon instance and try increasing the wait timeout.
- **Whisper model download:** The Docker image pre-downloads the Whisper "base" model for fast startup. If you use a different model, update the Dockerfile accordingly.
- **OpenRouter API issues:** Ensure your API key is valid and you have sufficient quota.

## Code Quality

- The codebase is modular and maintainable, with repeated logic extracted into helper functions.
- Logging is standardized using `print_flush` for consistent and immediate output.
- Environment variable access is robust and centralized via a single helper.
- All code changes are tested and must pass before commit.

## License

MIT

---

## Contributing

PRs and issues welcome!

- Please ensure all tests pass before submitting a PR.
- Follow the code style and modularity guidelines (see `AGENTS.md`).
- Refactor or extract helpers if you find repeated logic.
- Use `print_flush` for logging.

