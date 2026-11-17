"""Unified ASGI entry point: uvicorn app:app from the repository root."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("EVENT_MEMORY_ENABLED", "true")

from main import app  # noqa: E402,F401
