"""Vercel serverless function: /api/errors (logic lives in webcore.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webcore import ApiHandler  # noqa: E402


class handler(ApiHandler):
    pass
