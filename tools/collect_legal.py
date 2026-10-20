"""Preserve build-environment license notices without importing native SDKs."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import sys


def collect(destination: Path) -> None:
    if destination.is_symlink():
        raise RuntimeError("Legal output directory must not be a symlink.")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    # SDK packages are inventoried separately and excluded from downloadable
    # binaries until the corresponding-source distribution gate is complete.
    excluded = {"afk-grinder", "maafw", "maaagentbinary", "numpy", "strenum"}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "")
        if name.lower() in excluded:
            continue
        version = distribution.version
        label = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{name}-{version}")
        notices = []
        for file in distribution.files or []:
            parts = Path(str(file)).parts
            if (not parts or not parts[0].endswith(".dist-info")
                    or any(p in {".", ".."} for p in parts)):
                continue
            if not any(word in Path(str(file)).name.lower() for word in ("license", "copying", "notice")):
                continue
            source = Path(distribution.locate_file(file))
            if not source.is_file():
                continue
            relative = Path(label) / Path(*parts[1:])
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            notices.append({"file": relative.as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        records.append({"name": name, "version": version, "notices": notices,
                        "scope": "installed build dependency; not proof of runtime inclusion"})
    candidates = (Path(sys.base_prefix) / "LICENSE.txt",
                  Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt")
    for candidate in candidates:
        if candidate.is_file():
            shutil.copyfile(candidate, destination / "Python-runtime-LICENSE.txt")
            break
    else:
        raise RuntimeError("Python runtime license was not found; packaging stopped.")
    (destination / "build-dependencies.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
