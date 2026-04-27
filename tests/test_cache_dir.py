"""Tests para las helpers de cache_dir en smv_peru.client."""
import sys
from pathlib import Path

import pytest

from smv_peru.client import _default_cache_dir, _user_cache_dir


@pytest.mark.skipif(sys.platform != "darwin", reason="solo aplica en macOS")
def test_user_cache_dir_macos():
    """En macOS, el cache va a ~/Library/Caches/<app>/."""
    expected = Path.home() / "Library" / "Caches" / "smv-peru"
    assert _user_cache_dir("smv-peru") == expected


def test_default_cache_dir_uses_user_cache_when_no_env(monkeypatch):
    """Sin la env var SMV_PERU_CACHE_DIR, cae al user cache dir del SO."""
    monkeypatch.delenv("SMV_PERU_CACHE_DIR", raising=False)
    assert _default_cache_dir() == _user_cache_dir("smv-peru")


def test_default_cache_dir_respects_env_var(monkeypatch, tmp_path):
    """Si SMV_PERU_CACHE_DIR está seteada, manda sobre el default del SO."""
    custom = tmp_path / "mi-cache"
    monkeypatch.setenv("SMV_PERU_CACHE_DIR", str(custom))
    assert _default_cache_dir() == custom


def test_default_cache_dir_expands_tilde(monkeypatch):
    """El ~ en la env var se expande a la home del usuario."""
    monkeypatch.setenv("SMV_PERU_CACHE_DIR", "~/mi-cache")
    assert _default_cache_dir() == Path.home() / "mi-cache"
