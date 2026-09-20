"""Тесты конфигурации."""
import importlib

import pytest


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("VK_TOKEN", "xyz")
    monkeypatch.setenv("DEFAULT_AGE_FROM", "21")

    import config as cfg
    importlib.reload(cfg)

    assert cfg.settings.VK_TOKEN == "xyz"
    assert cfg.settings.DEFAULT_AGE_FROM == 21


def test_require_raises_when_missing(monkeypatch):
    monkeypatch.delenv("VK_TOKEN", raising=False)

    import config as cfg
    with pytest.raises(RuntimeError, match="VK_TOKEN"):
        importlib.reload(cfg)