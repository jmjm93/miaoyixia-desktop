"""Read-only bundled assets and writable per-user application files."""
import os
from pathlib import Path
import sys

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
DATA = ROOT / "data"


def user_dir():
    if not getattr(sys, "frozen", False):
        return ROOT
    directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Miaoyixia"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
