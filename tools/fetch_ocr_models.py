"""Explicit developer fetch of pinned OCR assets for private recognition builds.

The application never invokes this tool or downloads models at runtime.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from afk_grinder.recognition.ocr_models import COMMIT, MODELS, model_directory, validate_models


def main():
    destination = model_directory()
    if destination.is_symlink():
        raise SystemExit("Model destination cannot be a link.")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    curl = shutil.which("curl")
    if not curl:
        raise SystemExit("TLS-verifying curl is required for this developer tool.")
    records = []
    with tempfile.TemporaryDirectory(prefix="afk-ocr-") as temporary:
        for name, (source, size, digest) in MODELS.items():
            url = f"https://raw.githubusercontent.com/MaaXYZ/MaaCommonAssets/{COMMIT}/{source}"
            path = Path(temporary) / name
            subprocess.run([curl, "--fail", "--show-error", "--silent", "--location", "--proto", "=https",
                            "--proto-redir", "=https", "--max-time", "60", "--max-filesize", str(size),
                            "--output", str(path), url], check=True)
            if path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise SystemExit("Pinned OCR asset verification failed.")
            target = destination / name
            if target.exists() or target.is_symlink():
                raise SystemExit("Model destination already contains assets; verify or move it first.")
            shutil.copyfile(path, target)
            os.chmod(target, 0o600)
            records.append({"file": name, "url": url, "size": size, "sha256": digest})
    validate_models(destination)
    (destination / "PROVENANCE.json").write_text(json.dumps({"commit": COMMIT, "files": records}, indent=2) + "\n")
    print("Pinned local OCR assets verified. Private builds only; distribution gate remains closed.")


if __name__ == "__main__":
    main()
