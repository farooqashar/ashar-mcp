# Alternate entrypoint for hosts that look in api/. The real app lives in server.py.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import app  # noqa: E402,F401
