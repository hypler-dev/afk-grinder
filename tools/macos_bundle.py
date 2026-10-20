"""Stamp an unsigned local macOS PyInstaller bundle before local verification."""

from __future__ import annotations

from pathlib import Path
import plistlib
import re
import stat
import subprocess


_VERSION = re.compile(r"^\d+\.\d+\.\d+$", re.ASCII)


def _info_plist(bundle: Path) -> Path:
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("macOS bundle must be a real directory.")
    root = bundle.resolve(strict=True)
    contents = bundle / "Contents"
    try:
        contents_mode = contents.lstat().st_mode
    except FileNotFoundError as error:
        raise ValueError("macOS bundle is missing a real Contents directory.") from error
    if not stat.S_ISDIR(contents_mode):
        raise ValueError("macOS bundle is missing a real Contents directory.")
    info = contents / "Info.plist"
    try:
        mode = info.lstat().st_mode
    except FileNotFoundError as error:
        raise ValueError("macOS bundle is missing a real Contents/Info.plist file.") from error
    if not stat.S_ISREG(mode):
        raise ValueError("macOS bundle is missing a real Contents/Info.plist file.")
    try:
        info.resolve(strict=True).relative_to(root)
    except ValueError as error:
        raise ValueError("macOS bundle Info.plist escapes the bundle root.") from error
    return info


def stamp_unsigned_bundle_version(bundle: Path, version: str) -> None:
    """Set local unsigned bundle versions, then ad-hoc sign and verify it.

    This is for an unsigned local diagnostic bundle only.  It never selects a
    signing identity, accesses credentials, publishes an artifact, or creates
    release evidence.
    """
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("Bundle version must be numeric major.minor.patch.")
    info = _info_plist(Path(bundle))
    try:
        with info.open("rb") as source:
            contents = plistlib.load(source)
    except (OSError, ValueError) as error:
        raise ValueError("macOS bundle Info.plist is unreadable.") from error
    if not isinstance(contents, dict):
        raise ValueError("macOS bundle Info.plist must contain a dictionary.")

    contents["CFBundleShortVersionString"] = version
    contents["CFBundleVersion"] = version
    try:
        with info.open("wb") as destination:
            plistlib.dump(contents, destination)
    except (OSError, ValueError) as error:
        raise ValueError("macOS bundle Info.plist could not be written.") from error

    subprocess.run(["codesign", "--force", "--sign", "-", str(bundle)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
