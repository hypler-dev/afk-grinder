"""Small, non-sensitive build identity for the local Settings screen."""

import json
from pathlib import Path
import platform
import re
import sys

from . import __version__


def build_info() -> dict[str, str]:
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    system = "macos" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "unsupported"
    result = {"version": __version__, "commit": "development", "platform": f"{system}-{architecture}"}
    record = Path(__file__).with_name("build-info.json")
    try:
        if record.stat().st_size > 1024:
            return result
        metadata = json.loads(record.read_text(encoding="utf-8"))
        commit = metadata.get("commit")
        if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}(?:-dirty)?", commit):
            result["commit"] = commit
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return result
