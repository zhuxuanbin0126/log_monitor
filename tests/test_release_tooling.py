"""发布工具与版本文档一致性测试。"""

import importlib.util
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent.parent


def _load_build_release():
    spec = importlib.util.spec_from_file_location(
        "build_release", ROOT / "tools" / "build_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_versions_are_consistent():
    module = _load_build_release()
    assert module.check_versions() == config.VERSION


def test_version_format_is_four_segments():
    parts = config.VERSION.split('.')
    assert len(parts) == 4
    assert all(part.isdigit() for part in parts)


def test_changelog_contains_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"v{config.VERSION}" in changelog


def test_readme_mentions_current_version():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"v{config.VERSION}" in readme


def test_release_notes_document_exists():
    """当前版本必须有发布说明文档（文件名随版本号变化）。"""
    notes = ROOT / f"发布说明_V{config.VERSION}.md"
    assert notes.is_file(), f"缺少发布说明文档：{notes.name}"
    text = notes.read_text(encoding="utf-8")
    assert config.VERSION in text
    assert "已知限制" in text and "修复" in text
