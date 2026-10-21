"""Rebuild a compatible SDK and verify a separate private frozen copy.

This developer-only command never installs, publishes, grants permissions,
captures a window, or starts the application's input/UI modes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
from typing import Any

from afk_grinder.recognition.maa_adapter import (
    FRAME_CACHE_LIMIT, MAA_SOURCE_REVISION, PINNED_MAA_VERSION, REPLACEMENT_PROBE,
)
from tools.fetch_sdk_sources import prepare
from tools.macos_bundle import stamp_unsigned_bundle_version
from tools.sdk_bundle import validate_recognition_bundle


_HOSTS = {
    "macos-arm64": ("darwin", {"arm64", "aarch64"}, "arm64"),
    "macos-x64": ("darwin", {"x86_64", "amd64"}, "x86_64"),
    "windows-x64": ("win32", {"x86_64", "amd64"}, "AMD64"),
}
_STEMS = ("MaaFramework", "MaaUtils", "MaaCustomControlUnit")
_SOURCE_FILE = Path("source/MaaFramework/API/MaaFramework.cpp")
_SOURCE_SHA256 = "60b7a8c19c79d466d0be14b64e02a62a4c20c39a04af712a1eca64c40ad8f87d"
_PROBE_CPP = '''

// Synthetic loader probe for the private replacement experiment only.
extern "C" MAA_FRAMEWORK_API const char* AfkGrinderReplacementProbe()
{
    return "afk-grinder-sdk-replacement-v1";
}
'''
_OFF = (
    "WITH_ADB_CONTROLLER", "WITH_WIN32_CONTROLLER", "WITH_MACOS_CONTROLLER",
    "WITH_ANDROID_NATIVE_CONTROLLER", "WITH_PLAYCOVER_CONTROLLER", "WITH_GAMEPAD_CONTROLLER",
    "WITH_LINUX_CONTROLLER", "WITH_RECORD_CONTROLLER", "WITH_REPLAY_CONTROLLER",
    "WITH_DBG_CONTROLLER", "WITH_MAA_AGENT", "WITH_NODEJS_BINDING", "WITH_QUICKJS_BINDING",
    "BUILD_PICLI", "BUILD_SAMPLE", "BUILD_PIPELINE_TESTING", "BUILD_DLOPEN_TESTING",
    "BUILD_NODE_TEST", "BUILD_MACOS_TEST", "BUILD_LINUX_TEST", "ENABLE_CCACHE",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_host(label: str) -> None:
    _require(label in _HOSTS, "Unsupported SDK replacement target.")
    system, machines, _ = _HOSTS[label]
    _require(sys.platform == system and platform.machine().casefold() in machines,
             "SDK replacement target does not match the native host.")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(command: list[str], *, timeout: float = 30, **options: Any) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, timeout=timeout, **options)


def _read_json(path: Path, *, limit: int = 4096) -> dict[str, Any]:
    mode = path.lstat()
    _require(stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1 and mode.st_size <= limit,
             "SDK test metadata must be a bounded regular file.")
    def unique_pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "SDK test metadata contains duplicate keys.")
            result[key] = value
        return result
    def finite_float(value):
        result = float(value)
        _require(math.isfinite(result), "SDK test metadata contains a non-finite number.")
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                           parse_float=finite_float,
                           parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise ValueError("SDK test metadata must be strict JSON.") from None
    _require(type(value) is dict, "SDK test metadata must be an object.")
    return value


def _names(label: str) -> tuple[str, ...]:
    return tuple(f"{stem}.dll" if label == "windows-x64" else f"lib{stem}.dylib" for stem in _STEMS)


def _layout(bundle: Path, label: str) -> tuple[Path, Path]:
    if label == "windows-x64":
        return bundle / "_internal", bundle / "AFKGrinder.exe"
    return bundle / "Contents/Resources", bundle / "Contents/MacOS/AFKGrinder"


def _core_paths(bundle: Path, label: str) -> dict[str, list[Path]]:
    root = bundle.resolve(strict=True)
    data, _ = _layout(bundle, label)
    result = {}
    for name in _names(label):
        logical = data / "maa/bin" / name
        expected = logical.resolve(strict=True)
        expected.relative_to(root)
        reference_hash = _hash(expected)
        paths = {expected}
        for alias in bundle.rglob(name):
            target = alias.resolve(strict=True)
            target.relative_to(root)
            _require(target.is_file() and _hash(target) == reference_hash,
                     "Bundled SDK core copies disagree; replacement is ambiguous.")
            paths.add(target)
        result[name] = sorted(paths)
    return result


def _snapshot(bundle: Path, label: str) -> dict[str, str]:
    data, executable = _layout(bundle, label)
    paths = {executable.resolve(strict=True), (data / "afk_grinder/build-info.json").resolve(strict=True)}
    if label != "windows-x64":
        paths.add((bundle / "Contents/Info.plist").resolve(strict=True))
    for copies in _core_paths(bundle, label).values():
        paths.update(copies)
    root = bundle.resolve(strict=True)
    return {path.relative_to(root).as_posix(): _hash(path) for path in sorted(paths)}


def _native_architecture(path: Path, label: str) -> str:
    expected = _HOSTS[label][2]
    if label == "windows-x64":
        with path.open("rb") as stream:
            header = stream.read(64)
            _require(len(header) == 64 and header[:2] == b"MZ", "Expected a Windows PE image.")
            offset = struct.unpack_from("<I", header, 0x3C)[0]
            _require(64 <= offset <= 1024 * 1024, "Windows PE header offset is invalid.")
            stream.seek(offset)
            signature = stream.read(6)
        _require(len(signature) == 6 and signature[:4] == b"PE\0\0"
                 and struct.unpack_from("<H", signature, 4)[0] == 0x8664,
                 "SDK replacement must be Windows AMD64.")
        return expected
    actual = _run(["lipo", "-archs", str(path)], capture_output=True, text=True).stdout.strip()
    _require(actual == expected, "SDK replacement architecture did not match the host target.")
    return actual


def configure_command(cmake: str, source: Path, build: Path, label: str) -> list[str]:
    _require(label in _HOSTS, "Unsupported SDK replacement target.")
    command = [cmake, "-S", str(source), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
               f"-DCMAKE_INSTALL_PREFIX={build / 'install'}", f"-DMAA_HASH_VERSION={PINNED_MAA_VERSION}",
               "-DWITH_CUSTOM_CONTROLLER=ON"]
    command += [f"-D{option}=OFF" for option in _OFF]
    if label == "windows-x64":
        command += ["-A", "x64", "-DCMAKE_CONFIGURATION_TYPES=Release"]
    else:
        command += [f"-DCMAKE_OSX_ARCHITECTURES={_HOSTS[label][2]}", "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.3"]
    return command


def _source_outputs(build: Path, label: str) -> dict[str, Path]:
    result = {}
    for name in _names(label):
        candidates = [path for path in (build / "bin" / name, build / "bin/Release" / name) if path.exists()]
        _require(len(candidates) == 1 and not candidates[0].is_symlink() and candidates[0].is_file(),
                 "Source build did not produce one unambiguous core library.")
        result[name] = candidates[0]
    return result


def _trim_and_sign(path: Path) -> dict[str, Any]:
    output = _run(["otool", "-l", str(path)], capture_output=True, text=True).stdout
    rpaths = re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset", output)
    removed = 0
    for rpath in rpaths:
        if rpath.startswith("/"):
            _run(["install_name_tool", "-delete_rpath", rpath, str(path)], capture_output=True)
            removed += 1
        else:
            _require(rpath in {"@loader_path", "@executable_path"}, "Unexpected SDK replacement RPATH.")
    output = _run(["otool", "-l", str(path)], capture_output=True, text=True).stdout
    final = re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset", output)
    _require(set(final) == {"@loader_path", "@executable_path"}, "SDK replacement retains an unsafe RPATH.")
    _run(["codesign", "--force", "--sign", "-", str(path)], capture_output=True)
    return {"rpaths": final, "development_rpaths_removed": removed}


def _worker_environment(copy: Path, label: str) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("DYLD_") and key not in {"MAAFW_BINARY_PATH", "PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE"}}
    if label == "windows-x64":
        system_root = environment.get("SystemRoot", environment.get("SYSTEMROOT", ""))
        _require(bool(system_root) and Path(system_root).is_dir(), "Windows system directory is unavailable.")
        data, executable = _layout(copy, label)
        environment["PATH"] = os.pathsep.join(map(str, (data / "maa/bin", data, executable.parent,
                                                        Path(system_root) / "System32", Path(system_root))))
    else:
        environment["DYLD_PRINT_LIBRARIES"] = "1"
    return environment


def _frozen_probe(copy: Path, work: Path, label: str) -> tuple[dict[str, Any], list[str]]:
    _, executable = _layout(copy, label)
    report_path = work / "sdk-worker.json"
    completed = _run([str(executable), "--sdk-worker", "--sdk-report", str(report_path), "--sdk-replacement-probe"],
                     timeout=30, cwd=work, env=_worker_environment(copy, label), capture_output=True, text=True)
    _require(completed.returncode == 0, "Frozen SDK replacement worker did not exit successfully.")
    payload = _read_json(report_path, limit=65_536)
    expected = {"sdk_version": PINNED_MAA_VERSION, "native_version": PINNED_MAA_VERSION,
                "source_revision": MAA_SOURCE_REVISION, "cpu_only": True, "frame_cache_limit": FRAME_CACHE_LIMIT,
                "persistent_images": False, "persistent_logs": False, "native_input": False,
                "capture_source": "synthetic", "custom_controller": "input callbacks disabled",
                "cancellation": "passed", "replacement_probe": REPLACEMENT_PROBE,
                "synthetic_template_match": "passed"}
    report = payload.get("report")
    if label == "windows-x64":
        from afk_grinder.recognition.windows_loader import validate_windows_sdk_loads
        _require(type(report) is dict and "windows_sdk_loads" in report,
                 "Frozen Windows SDK load observation is missing.")
        expected["windows_sdk_loads"] = validate_windows_sdk_loads(copy, report["windows_sdk_loads"])
    _require(set(payload) == {"ok", "report"} and payload["ok"] is True and type(report) is dict
             and set(report) == set(expected)
             and all(type(report[key]) is type(value) and report[key] == value for key, value in expected.items()),
             "Frozen source-built SDK replacement diagnostic did not pass.")
    loaded = set()
    if label != "windows-x64":
        root = copy.resolve(strict=True)
        for line in completed.stderr.splitlines():
            match = re.search(r"\s(/.*)$", line)
            if not match:
                continue
            path = Path(match.group(1))
            if path.name.startswith(("libMaa", "libfastdeploy", "libonnxruntime", "libopencv", "libwebgpu_dawn")):
                loaded.add(path.resolve(strict=True).relative_to(root).as_posix())
        for name in _names(label):
            _require(any(Path(item).name == name for item in loaded), "Frozen worker did not load all replaced cores from its copy.")
        for prefix in ("libfastdeploy", "libonnxruntime", "libopencv", "libwebgpu_dawn"):
            _require(any(Path(item).name.startswith(prefix) for item in loaded), "Frozen SDK dependency load was not observed.")
    return expected, sorted(loaded)


def verify(label: str, bundle: Path, work: Path, output: Path, commit: str) -> dict[str, Any]:
    from tools.sdk_build_dependencies import load_dependencies, prepare_dependencies

    require_host(label)
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "Expected a full source commit ID.")
    _require(not bundle.is_symlink() and bundle.is_dir(), "SDK input bundle must be a real directory.")
    bundle = bundle.resolve(strict=True)
    validate_recognition_bundle(bundle, sys.platform)
    data, executable = _layout(bundle, label)
    metadata = _read_json(data / "afk_grinder/build-info.json")
    _require(metadata.get("commit") == commit and metadata.get("version") == "0.2.0", "SDK input bundle source/version mismatch.")
    _native_architecture(executable, label)
    for path in (work, output):
        _require(not path.exists() and not path.is_symlink(), "SDK test work and report destinations must be new.")
        parent = path.parent.resolve(strict=True)
        _require(not parent.is_relative_to(bundle), "SDK test output cannot be inside the original app.")
    work = work.parent.resolve(strict=True) / work.name
    output = output.parent.resolve(strict=True) / output.name
    _require(not output.is_relative_to(work) and not work.is_relative_to(output), "SDK test report must be outside its work directory.")
    cmake = shutil.which("cmake")
    _require(cmake is not None, "CMake 3.28 or newer is required.")
    cmake_version = _run([cmake, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    version = re.fullmatch(r"cmake version (\d+)\.(\d+)\.\d+(?:[.-].*)?", cmake_version)
    _require(version is not None and tuple(map(int, version.groups())) >= (3, 28), "CMake 3.28 or newer is required.")
    before = _snapshot(bundle, label)
    work.mkdir(mode=0o700)
    prepared = prepare(work / "sources")
    source = prepared / "source/MaaFramework"
    dependency = load_dependencies()[label]
    extracted = prepare_dependencies(label, work / "dependencies")
    prefix = source / "source/MaaUtils/MaaDeps"
    for relative in (Path("vcpkg/installed"), Path("runtime")):
        target = prefix / relative
        _require(not target.exists() and not target.is_symlink(), "Binary dependencies would overwrite pinned source.")
        shutil.move(str(extracted / relative), str(target))
    probe_source = source / _SOURCE_FILE
    _require(_hash(probe_source) == _SOURCE_SHA256, "Pinned SDK probe source changed unexpectedly.")
    probe_source.write_bytes(probe_source.read_bytes() + _PROBE_CPP.encode("ascii"))
    build = work / "native-build"
    _run(configure_command(cmake, source, build, label), timeout=180)
    _run([cmake, "--build", str(build), "--config", "Release", "--target", "MaaFramework", "--parallel", "2"], timeout=900)
    built = _source_outputs(build, label)
    copies = work / "replacement"
    copies.mkdir()
    copy = copies / bundle.name
    shutil.copytree(bundle, copy, symlinks=True)
    records = []
    for name, targets in _core_paths(copy, label).items():
        architecture = _native_architecture(built[name], label)
        for target in targets:
            original_hash = _hash(target)
            shutil.copyfile(built[name], target)
            details = _trim_and_sign(target) if label != "windows-x64" else {}
            _require(_hash(target) != original_hash, "Replacement library is indistinguishable from the original.")
            records.append({"name": name, "path": target.relative_to(copy).as_posix(), "architecture": architecture,
                            "original_sha256": original_hash, "built_sha256": _hash(built[name]),
                            "replacement_sha256": _hash(target), **details})
    validate_recognition_bundle(copy, sys.platform)
    if label != "windows-x64":
        stamp_unsigned_bundle_version(copy, metadata["version"])
    sdk_report, loaded = _frozen_probe(copy, work, label)
    after = _snapshot(bundle, label)
    _require(before == after, "Original application changed during the private replacement test.")
    sources = json.loads((prepared / "sdk_sources.json").read_text(encoding="utf-8"))
    receipt = {"schema_version": 2, "label": label, "source_commit": commit, "sdk_version": PINNED_MAA_VERSION,
               "cmake_version": cmake_version, "sources": [{key: item[key] for key in ("name", "commit", "sha256")} for item in sources["components"]],
               "binary_build_dependency": {"url": dependency.url, "sha256": dependency.sha256, "triplet": dependency.triplet},
               "probe_source_original_sha256": _SOURCE_SHA256, "probe_source_modified_sha256": _hash(probe_source),
               "libraries": records, "sdk_report": sdk_report, "mac_loaded_sdk_libraries": loaded,
               "windows_sdk_loads": sdk_report.get("windows_sdk_loads"),
               "loader_evidence_scope": "Observed synthetic replacement worker only; not all possible lazy imports.",
               "originals_before": before, "originals_after": after, "originals_unchanged": True,
               "signature": "not modified on Windows" if label == "windows-x64" else "local ad-hoc; deep strict verified",
               "screen_capture": False, "native_input": False, "sdk_publication_gate": "closed"}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, choices=tuple(_HOSTS))
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    verify(args.label, args.bundle, args.work, args.output, args.commit)
    print(f"Private source-built SDK replacement passed for {args.label}. SDK publication remains blocked.")


if __name__ == "__main__":
    main()
