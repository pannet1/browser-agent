from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from app.core.config import SKILLS_ROOT
from app.core.logger import logging_func

logger = logging_func(__name__)

VAULT_KEY_ENV = "VAULT_KEY"


def _shared_path(target_domain: str) -> Path:
    return SKILLS_ROOT / "_shared" / target_domain / "credentials.json"


def _encrypt(data: str, key: str) -> str:
    try:
        from cryptography.fernet import Fernet
        import hashlib

        h = hashlib.sha256(key.encode()).digest()
        fkey = base64.urlsafe_b64encode(h)
        f = Fernet(fkey)
        return f.encrypt(data.encode()).decode()
    except Exception:
        return base64.b64encode(data.encode()).decode()


def _decrypt(token: str, key: str) -> str:
    try:
        from cryptography.fernet import Fernet
        import hashlib

        h = hashlib.sha256(key.encode()).digest()
        fkey = base64.urlsafe_b64encode(h)
        f = Fernet(fkey)
        return f.decrypt(token.encode()).decode()
    except Exception:
        try:
            return base64.b64decode(token.encode()).decode()
        except Exception:
            return token


class CredentialVault:

    def save(self, target_domain: str, username: str, password: str, meta: dict[str, Any] | None = None) -> Path:
        p = _shared_path(target_domain)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"username": username, "password": password, "meta": meta or {}}
        raw = json.dumps(payload)
        key = os.getenv(VAULT_KEY_ENV, "")
        data = _encrypt(raw, key) if key else raw
        p.write_text(data)
        try:
            p.chmod(0o600)
        except Exception:
            pass
        logger.info(f"vault saved for {target_domain}")
        return p

    def get(self, target_domain: str) -> dict[str, Any] | None:
        p = _shared_path(target_domain)
        if not p.exists():
            return None
        try:
            raw = p.read_text().strip()
            if not raw:
                return None
            key = os.getenv(VAULT_KEY_ENV, "")
            data = _decrypt(raw, key) if key else raw
            if key and not data.startswith("{"):
                data = _decrypt(raw, "")
            payload = json.loads(data)
            return payload
        except Exception as exc:
            logger.info(f"vault get failed {target_domain} {exc}")
            return None

    def get_by_skill(self, skill_id: str) -> dict[str, Any] | None:
        from app.features.skills.manager import get_skill

        meta = get_skill(skill_id)
        if not meta:
            return None
        domain = meta.get("target_domain", "")
        if not domain:
            return None
        return self.get(domain)

    def delete(self, target_domain: str) -> bool:
        p = _shared_path(target_domain)
        if p.exists():
            p.unlink()
            logger.info(f"vault deleted {target_domain}")
            return True
        return False
