"""Configuration is documented and production defaults are safe."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
REFERENCE = BACKEND.parent / "docs" / "operations" / "CONFIGURATION_REFERENCE.md"


def test_every_setting_is_in_the_committed_configuration_reference():
    if not REFERENCE.exists():
        pytest.skip("docs not present in this checkout")
    text = REFERENCE.read_text()
    missing = [n for n in Settings.model_fields if f"`{n}`" not in text]
    assert missing == [], f"regenerate with scripts/gen_config_reference.py; missing: {missing}"
    assert subprocess.run([sys.executable, "scripts/gen_config_reference.py", "--check"], cwd=BACKEND).returncode == 0


def test_reference_lists_numeric_token_lifetimes_as_values_not_secrets():
    if not REFERENCE.exists():
        pytest.skip("docs not present in this checkout")
    text = REFERENCE.read_text()
    assert "| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | `30` |" in text
    assert "dev-only-secret" in text and text.count("<redacted>") <= 1


def _start(env_overrides):
    env = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "ENVIRONMENT", "CORS_ALLOWED_ORIGINS", "DATABASE_URL")}
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND, env=env, capture_output=True, text=True)


def test_production_refuses_placeholder_short_and_wildcard_configuration():
    good = "x" * 48
    assert _start({"ENVIRONMENT": "production", "SECRET_KEY": "dev-only-secret-change-me-in-production"}).returncode != 0
    assert _start({"ENVIRONMENT": "production", "SECRET_KEY": "short"}).returncode != 0
    assert _start({"ENVIRONMENT": "production", "SECRET_KEY": good, "CORS_ALLOWED_ORIGINS": "*"}).returncode != 0
    ok = _start({"ENVIRONMENT": "production", "SECRET_KEY": good, "CORS_ALLOWED_ORIGINS": "https://aegis.example.org"})
    assert ok.returncode == 0, ok.stderr[-400:]


def test_production_disables_interactive_docs_by_default():
    out = subprocess.run(
        [sys.executable, "-c", "from app.core.config import get_settings as g; s=g(); print(s.docs_enabled)"],
        cwd=BACKEND, env={**os.environ, "ENVIRONMENT": "production", "SECRET_KEY": "x" * 48}, capture_output=True, text=True,
    )
    assert out.stdout.strip() == "False"
