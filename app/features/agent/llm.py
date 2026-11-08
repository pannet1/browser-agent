"""
LLM adapter: Orca's managed agent (`codex exec`).

One non-interactive, single-turn completion per call, authenticated through
the user's Orca/ChatGPT account. The final assistant message is captured
verbatim via `--output-last-message` to avoid parsing hook/status noise.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.logger import logging_func

logger = logging_func(__name__)


def _strip_code_fences(text: str) -> str:
    """ReAct controllers expect parseable JSON; codex may wrap it in fences."""
    if "```" not in text:
        return text
    # Prefer the first fenced block.
    start = text.find("```")
    end = text.find("```", start + 3)
    if start == -1 or end == -1:
        return text
    block = text[start + 3:end]
    nl = block.find("\n")
    if nl != -1 and block[:nl].strip().isalpha():  # ```json style fence label
        block = block[nl + 1:]
    return block.strip()


class OrcaLLM:
    """LLM adapter backed by Orca's managed agent (``codex exec``)."""

    def __init__(self, binary: str = "codex", model: str = "", timeout: int = 300) -> None:
        self.binary = binary
        self.model = model
        self.timeout = timeout

    def _available(self) -> bool:
        return shutil.which(self.binary) is not None

    def complete(self, prompt: str) -> str:
        """Run a single codex exec completion and return the final message."""
        if not self._available():
            logger.warning(f"[LLM] {self.binary} not found on PATH")
            return ""
        with tempfile.TemporaryDirectory(prefix="browser-agent-llm-") as tmp:
            out_path = os.path.join(tmp, "last-message.txt")
            cmd = [self.binary, "exec", "--skip-git-repo-check", "-s", "read-only"]
            if self.model:
                cmd += ["-m", self.model]
            cmd += ["-o", out_path, prompt]
            logger.info(f"[LLM] Orca codex exec (model: {self.model or 'default'})")
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
            except subprocess.TimeoutExpired:
                logger.warning(f"[LLM] codex exec timed out after {self.timeout}s")
                return ""
            answer = Path(out_path).read_text(errors="replace").strip() if os.path.exists(out_path) else ""
            answer = _strip_code_fences(answer)
            if proc.returncode != 0 or not answer:
                tail = (proc.stderr or "").strip().splitlines()[-2:]
                logger.warning(f"[LLM] codex exec failed (code {proc.returncode}): {' | '.join(tail) or 'no stderr'}")
                return ""
            logger.info("[LLM] Orca codex exec succeeded")
            return answer


# Singleton instance
_orca_default_llm: OrcaLLM | None = None


def get_llm(model: str = "", timeout: int = 300) -> OrcaLLM:
    """Return the Orca LLM adapter singleton.

    Orca/codex handles its own model selection, so there is no model chain or
    attempt budget to configure.
    """
    global _orca_default_llm
    if _orca_default_llm is None:
        _orca_default_llm = OrcaLLM(model=model, timeout=timeout)
    return _orca_default_llm
