#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布构建脚本：版本校验 → PyInstaller 打包 → 运行时资源 → SHA256 清单 → ZIP。

用法（仓库根目录）：
    python tools/build_release.py --check-only     # 只校验版本一致性
    python tools/build_release.py                  # 完整构建（含 zip）
    python tools/build_release.py --skip-build     # 跳过 PyInstaller，仅重组 release/
    python tools/build_release.py --no-zip         # 不生成 zip
"""

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
RELEASE = ROOT / "release"

VERSION_RE = re.compile(r"^VERSION\s*=\s*'([^']+)'", re.MULTILINE)
FILEVERS_RE = re.compile(r"filevers=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)")

RUNTIME_ITEMS = [
    "tools",
    "device_info.json",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "用户手册.md",
    "用户手册.pdf",
    "设备监控系统操作手册.pdf",
    "发布说明_V1.0.6.0.md",
]


def get_config_version() -> str:
    text = (ROOT / "config.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise RuntimeError("config.py 中未找到 VERSION")
    return match.group(1)


def get_version_info_version() -> str:
    text = (ROOT / "version_info.txt").read_text(encoding="utf-8")
    match = FILEVERS_RE.search(text)
    if not match:
        raise RuntimeError("version_info.txt 中未找到 filevers")
    return ".".join(match.groups())


def check_versions() -> str:
    """校验 config.py 与 version_info.txt 版本一致，返回版本号。"""
    config_version = get_config_version()
    info_version = get_version_info_version()
    if config_version != info_version:
        raise SystemExit(
            f"[错误] 版本不一致: config.VERSION={config_version}, "
            f"version_info.filevers={info_version}"
        )
    print(f"[ok] 版本一致: {config_version}")
    return config_version


def run_pyinstaller() -> None:
    print("[1/4] PyInstaller 打包...")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "log_monitor.spec"],
        cwd=str(ROOT),
        check=True,
    )


def _ignore_runtime(_directory, names):
    return [name for name in names if name in {"__pycache__", ".pytest_cache"} or name.endswith(".pyc")]


def _clean_release() -> None:
    """清理旧发布内容；跳过被运行中程序占用的 output/。"""
    if not RELEASE.exists():
        return
    for child in list(RELEASE.iterdir()):
        if child.name == "output":
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except PermissionError:
                continue


def _in_package(path: Path) -> bool:
    """发布包不包含运行数据目录（output/）。"""
    return not path.relative_to(RELEASE).parts[0].startswith("output")


def stage_release() -> None:
    print("[2/4] 组装 release 目录...")
    exe = DIST / "log_monitor.exe"
    if not exe.is_file():
        raise SystemExit(f"[错误] 未找到 {exe}，请先执行打包")

    RELEASE.mkdir(parents=True, exist_ok=True)
    _clean_release()

    shutil.copy2(exe, RELEASE / exe.name)
    for name in RUNTIME_ITEMS:
        src = ROOT / name
        dst = RELEASE / name
        if src.is_dir():
            shutil.copytree(src, dst, ignore=_ignore_runtime, dirs_exist_ok=True)
        elif src.is_file():
            shutil.copy2(src, dst)


def write_sha256_manifest() -> Path:
    print("[3/4] 生成 SHA256 清单...")
    manifest = RELEASE / "SHA256SUMS.txt"
    lines = []
    for path in sorted(RELEASE.rglob("*")):
        if not path.is_file() or path == manifest or not _in_package(path):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rel = path.relative_to(RELEASE).as_posix()
        lines.append(f"{digest}  {path.stat().st_size:>12}  {rel}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def make_zip(version: str) -> Path:
    print("[4/4] 生成 zip...")
    zip_path = RELEASE / f"log_monitor_v{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(RELEASE.rglob("*")):
            if not path.is_file() or path == zip_path or not _in_package(path):
                continue
            zf.write(path, path.relative_to(RELEASE).as_posix())
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="log_monitor 发布构建")
    parser.add_argument("--check-only", action="store_true", help="只校验版本一致性")
    parser.add_argument("--skip-build", action="store_true", help="跳过 PyInstaller")
    parser.add_argument("--no-zip", action="store_true", help="不生成 zip")
    args = parser.parse_args()

    version = check_versions()
    if args.check_only:
        return 0

    if not args.skip_build:
        run_pyinstaller()
    stage_release()
    manifest = write_sha256_manifest()
    print(f"[ok] 发布目录: {RELEASE}")
    print(f"[ok] 清单: {manifest}")

    if not args.no_zip:
        zip_path = make_zip(version)
        print(f"[ok] 压缩包: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
