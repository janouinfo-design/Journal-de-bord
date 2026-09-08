"""Garde-fou : la fixture DEV du trajet privé ne doit JAMAIS être chargée en prod.

PRODUCTION => DEV_PRIVATE_FIXTURE_DISABLED (fail-closed).
"""
import importlib

import app.mock_navixy as m


def _reload(monkeypatch, app_env=None, flag=None):
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    if flag is None:
        monkeypatch.delenv("ENABLE_DEV_PRIVATE_FIXTURE", raising=False)
    else:
        monkeypatch.setenv("ENABLE_DEV_PRIVATE_FIXTURE", flag)
    importlib.reload(m)
    return m


def test_fixture_enabled_in_development(monkeypatch):
    mod = _reload(monkeypatch, app_env="development")
    assert mod.dev_private_fixture_enabled() is True


def test_fixture_enabled_in_preview(monkeypatch):
    mod = _reload(monkeypatch, app_env="preview")
    assert mod.dev_private_fixture_enabled() is True


def test_fixture_disabled_in_production(monkeypatch):
    mod = _reload(monkeypatch, app_env="production")
    assert mod.dev_private_fixture_enabled() is False


def test_fixture_disabled_when_app_env_absent(monkeypatch):
    """Fail-closed : APP_ENV absent -> considéré production -> désactivé."""
    mod = _reload(monkeypatch, app_env=None)
    assert mod.dev_private_fixture_enabled() is False


def test_fixture_disabled_by_explicit_flag_even_in_dev(monkeypatch):
    mod = _reload(monkeypatch, app_env="development", flag="false")
    assert mod.dev_private_fixture_enabled() is False


def test_fixture_disabled_for_unknown_env(monkeypatch):
    mod = _reload(monkeypatch, app_env="staging")
    assert mod.dev_private_fixture_enabled() is False
