"""Native backend factory.

Platform modules stay unloaded until a backend is requested. This keeps dry-run
and source validation usable on hosts without Windows or macOS dependencies.
"""

import sys

from afk_grinder.models import Backend


def create_backend() -> Backend:
    """Create native backend for supported local desktop platform."""
    if sys.platform == "win32":
        from afk_grinder.backends.windows import WindowsBackend

        return WindowsBackend()
    if sys.platform == "darwin":
        from afk_grinder.backends.macos import MacOSBackend

        return MacOSBackend()
    raise RuntimeError(
        "Live input is supported only on Windows and macOS; dry run remains available."
    )
