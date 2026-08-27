from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.features.credentials.detector import is_login_success
from app.features.credentials.injector import pre_inject
from app.features.credentials.vault import CredentialVault


@pytest.fixture(autouse=True)
def tmp_vault(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import app.features.credentials.vault as vmod
    import app.core.config as cfg
    monkeypatch.setattr(cfg, "SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setattr(vmod, "SKILLS_ROOT", tmp_path / "skills")
    return tmp_path


class FakePage:

    def __init__(self, ax: str = "", url: str = "https://example.com") -> None:
        self.url = url
        self._ax = ax
        self.fills: list[tuple[str, str]] = []
        self.values: dict[str, str] = {"input[name='username']": "alice", "input[name='password']": "secret"}

    async def fill(self, selector: str, text: str, timeout: int = 1000) -> None:
        if "missing" in selector:
            raise RuntimeError("no selector")
        self.fills.append((selector, text))

    async def input_value(self, selector: str) -> str:
        return self.values.get(selector, "")

    @property
    def accessibility(self) -> object:
        outer = self

        class A:
            async def snapshot(self) -> dict[str, str]:
                return {"name": outer._ax}

        return A()


def test_vault_save_get_delete(tmp_vault: Path) -> None:
    vault = CredentialVault()
    vault.save("example.com", "alice", "secret")
    creds = vault.get("example.com")
    assert creds is not None
    assert creds["username"] == "alice"
    assert creds["password"] == "secret"
    assert vault.delete("example.com") is True
    assert vault.get("example.com") is None


def test_vault_encrypted_with_key(monkeypatch: pytest.MonkeyPatch, tmp_vault: Path) -> None:
    monkeypatch.setenv("VAULT_KEY", "test-key-123")
    vault = CredentialVault()
    vault.save("example.com", "bob", "pass123")
    p = tmp_vault / "skills" / "_shared" / "example.com" / "credentials.json"
    raw = p.read_text()
    assert "bob" not in raw
    creds = vault.get("example.com")
    assert creds is not None
    assert creds["username"] == "bob"


def test_detector_login_success() -> None:
    assert is_login_success("Welcome dashboard", "https://example.com/home") is True
    assert is_login_success("login form", "https://example.com/login") is False
    assert is_login_success("", "https://example.com/home", before_url="https://example.com/login") is True


@pytest.mark.asyncio
async def test_injector_pre_inject(tmp_vault: Path) -> None:
    vault = CredentialVault()
    vault.save("example.com", "alice", "secret")
    page = FakePage()
    res = await pre_inject(page, "example.com", vault)
    assert res["status"] == "injected"
    assert any("secret" in v for _, v in page.fills)


@pytest.mark.asyncio
async def test_injector_no_creds(tmp_vault: Path) -> None:
    vault = CredentialVault()
    page = FakePage()
    res = await pre_inject(page, "missing.com", vault)
    assert res["status"] == "no_creds"


@pytest.mark.asyncio
async def test_detector_captures(tmp_vault: Path) -> None:
    from app.features.credentials.detector import detect_and_capture

    vault = CredentialVault()
    page = FakePage(ax="Welcome dashboard", url="https://example.com/home")
    res = await detect_and_capture(page, "example.com", before_url="https://example.com/login", vault=vault)
    assert res is not None
    assert res["target_domain"] == "example.com"
    creds = vault.get("example.com")
    assert creds is not None
