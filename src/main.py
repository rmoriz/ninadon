#!/usr/bin/env python3
import argparse
import tempfile
import os

def main():
    parser = argparse.ArgumentParser(description="Download, transcribe, summarize, and post video.")
    parser.add_argument('url', help='Video URL (YouTube, Instagram, TikTok)')
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Working in temp dir: {tmpdir}")
        # TODO: Download, transcribe, summarize, post, cleanup

if __name__ == "__main__":
    main()
