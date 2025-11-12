"""
Entry point for running Scribe as a module.

Usage:
    python -m scribe transcribe audio.wav
    python -m scribe record --name "Meeting"
    python -m scribe info
"""

from scribe.cli.main import app

if __name__ == "__main__":
    app()
