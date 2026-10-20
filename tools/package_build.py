"""Create local CI artifacts from a target-OS PyInstaller build.

This tool packages only the build output already created by ``tools/build.py``.
It never signs, uploads, or runs the application.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import sys
import tarfile
import tomllib
import zipfile


LABELS = {
    "windows-x64": ("win32", {"amd64", "x86_64"}),
    "macos-arm64": ("darwin", {"arm64", "aarch64"}),
    "macos-x64": ("darwin", {"x86_64", "amd64"}),
}
COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{40}")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _validate_commit(commit: str) -> None:
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("--commit must be exactly 40 hexadecimal characters.")


def _validate_runtime(label: str, system: str, machine: str) -> None:
    if label not in LABELS:
        raise ValueError("--label must be one of: windows-x64, macos-arm64, macos-x64.")
    required_system, machines = LABELS[label]
    if system != required_system or machine.lower() not in machines:
        raise ValueError(
            f"{label} packaging requires {required_system} on one of "
            f"{', '.join(sorted(machines))}; found {system}/{machine}."
        )


def _require_regular_file(path: Path, description: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing trusted {description}: {path}")


def _bundle_for_label(root: Path, label: str) -> tuple[Path, str, bool]:
    dist = root / "dist"
    if label == "windows-x64":
        bundle = dist / "AFKGrinder"
        if bundle.is_symlink() or not bundle.is_dir():
            raise ValueError(f"Missing trusted Windows bundle: {bundle}")
        _require_regular_file(bundle / "AFKGrinder.exe", "Windows executable")
        return bundle, "AFKGrinder", False
    bundle = dist / "AFKGrinder.app"
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError(f"Missing trusted macOS app bundle: {bundle}")
    _require_regular_file(bundle / "Contents" / "MacOS" / "AFKGrinder", "macOS executable")
    return bundle, "AFKGrinder.app", True


def _entries(bundle: Path, *, allow_symlinks: bool) -> list[Path]:
    """Return safe paths below a built bundle without following symlinks."""
    bundle = bundle.resolve()
    entries: list[Path] = [bundle]
    for directory, dirnames, filenames in os.walk(bundle, topdown=True, followlinks=False):
        current = Path(directory)
        for name in sorted(dirnames + filenames):
            path = current / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                if not allow_symlinks:
                    raise ValueError(f"Untrusted symlink in Windows bundle: {path}")
                if not _inside(path, bundle):
                    raise ValueError(f"Untrusted symlink target outside app bundle: {path}")
                if name in dirnames:
                    dirnames.remove(name)
            elif stat.S_ISDIR(mode) or stat.S_ISREG(mode):
                if not _inside(path, bundle):
                    raise ValueError(f"Untrusted artifact path outside bundle: {path}")
            else:
                raise ValueError(f"Unsupported artifact file type: {path}")
            entries.append(path)
    return entries


def _archive_name(label: str) -> str:
    suffix = ".zip" if label == "windows-x64" else ".tar.gz"
    return f"AFKGrinder-{label}{suffix}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_symlink():
        digest.update(os.readlink(path).encode("utf-8", "surrogateescape"))
    else:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as source:
        return str(tomllib.load(source)["project"]["version"])


def _metadata(
    *, root: Path, label: str, commit: str, archive_name: str, timestamp: datetime
) -> bytes:
    return (json.dumps(
        {
            "archive_filename": archive_name,
            "commit": commit,
            "label": label,
            "machine": platform.machine(),
            "package_version": _version(root),
            "platform": sys.platform,
            "python_version": platform.python_version(),
            "timestamp_utc": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "validation": "No game validation performed.",
            "warning": "Unsigned prototype; no signing or notarization performed.",
        },
        indent=2,
        sort_keys=True,
    ) + "\n").encode("utf-8")


def _outer_manifest(archive: Path, build_info: Path) -> bytes:
    """Create standard pre-extraction hashes for the artifact and its metadata."""
    records = [(archive.name, _sha256(archive)), (build_info.name, _sha256(build_info))]
    return "".join(f"{digest}  {name}\n" for name, digest in sorted(records)).encode("utf-8")


def _zip_add(archive: zipfile.ZipFile, path: Path, name: str) -> None:
    if path.is_dir():
        info = zipfile.ZipInfo(name.rstrip("/") + "/")
        info.external_attr = (path.stat().st_mode & 0o777) << 16 | 0x10
        archive.writestr(info, b"")
    else:
        archive.write(path, name)


def _tar_add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    archive.addfile(info, fileobj=__import__("io").BytesIO(payload))


def _tar_add(archive: tarfile.TarFile, path: Path, name: str) -> None:
    info = archive.gettarinfo(str(path), arcname=name)
    if info.isreg():
        with path.open("rb") as source:
            archive.addfile(info, source)
    else:
        archive.addfile(info)


def package_archive(
    root: Path,
    label: str,
    commit: str,
    output: Path | None = None,
    *,
    system: str | None = None,
    machine: str | None = None,
    timestamp: datetime | None = None,
) -> Path:
    """Package the current target-OS build and return the archive path."""
    root = root.resolve()
    _validate_commit(commit)
    _validate_runtime(label, system or sys.platform, machine or platform.machine())
    bundle, top_name, allow_symlinks = _bundle_for_label(root, label)
    entries = _entries(bundle, allow_symlinks=allow_symlinks)
    output = (output or root / "artifact-output").resolve()
    if not _inside(output, root) or _inside(output, root / "dist"):
        raise ValueError("--output must be inside the repository and outside dist/.")
    output.mkdir(parents=True, exist_ok=True)
    if not _inside(output, root):
        raise ValueError("--output resolves outside the repository.")

    archive_name = _archive_name(label)
    destination = output / archive_name
    build_info = _metadata(
        root=root,
        label=label,
        commit=commit,
        archive_name=archive_name,
        timestamp=timestamp or datetime.now(timezone.utc),
    )
    if label == "windows-x64":
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in entries:
                relative = path.relative_to(bundle)
                name = (PurePosixPath(top_name) / PurePosixPath(relative.as_posix())).as_posix()
                _zip_add(archive, path, name)
            archive.writestr("BUILD_INFO.json", build_info)
    else:
        with tarfile.open(destination, "w:gz", dereference=False) as archive:
            for path in entries:
                relative = path.relative_to(bundle)
                name = (PurePosixPath(top_name) / PurePosixPath(relative.as_posix())).as_posix()
                _tar_add(archive, path, name)
            _tar_add_bytes(archive, "BUILD_INFO.json", build_info)
    external_build_info = output / "BUILD_INFO.json"
    external_build_info.write_bytes(build_info)
    (output / "SHA256SUMS.txt").write_bytes(_outer_manifest(destination, external_build_info))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Package a built AFK Grinder CI artifact.")
    parser.add_argument("--label", required=True, choices=sorted(LABELS))
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifact-output"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        archive = package_archive(root, args.label, args.commit, root / args.output)
    except ValueError as error:
        parser.error(str(error))
    print(archive)


if __name__ == "__main__":
    main()
