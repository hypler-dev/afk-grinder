"""Locate Tcl/Tk data shipped with a source Python virtual environment."""

import os
from pathlib import Path
import sys


def configure_tk() -> None:
    # PyInstaller's runtime hook configures its own bundled data directories.
    if getattr(sys, "frozen", False):
        return
    base = Path(sys.base_prefix)
    for parent in (base / "lib", base / "tcl"):
        tcl = parent / "tcl8.6"
        tk = parent / "tk8.6"
        if (tcl / "init.tcl").is_file() and (tk / "tk.tcl").is_file():
            os.environ.setdefault("TCL_LIBRARY", str(tcl))
            os.environ.setdefault("TK_LIBRARY", str(tk))
            return
