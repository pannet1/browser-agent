"""
LLM adapter using the `pi` binary (same pattern as orchestrator project).

Runs `pi -p <prompt> --mode json --model <model>` and extracts the final assistant text.
"""
from __future__ import annotations

import io
import json
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

from app.core.logger import logging_func

logger = logging_func(__name__)

# Default model chain (free models) - same as orchestrator
PROVIDER_PREFERENCE: tuple[str, ...] = (
    "opencode",
    "opencode-go",
    "openrouter",
    "llama-swap",
)

LOCAL_FALLBACK = "llama-swap/qwen2.5-coder-7b-instruct"

DEFAULT_MODEL_CHAIN: tuple[str, ...] = (
    "openrouter/poolside/laguna-s-2.1:free",
    "openrouter/cohere/north-mini-code:free",
    "opencode/nemotron-3-ultra-free",
    "opencode/deepseek-v4-flash-free",
    "opencode/laguna-s-2.1-free",
    LOCAL_FALLBACK,
)

_model_cache: list[str] | None = None
_model_cache_time: float = 0.0
MODEL_CACHE_TTL = 300.0


def _pi_binary() -> str | None:
    return shutil.which("pi")


def query_provider_models(force: bool = False) -> list[str]:
    """Query `pi --list-models` and return all `provider/model` ids."""
    global _model_cache, _model_cache_time
    now = time.time()
    if not force and _model_cache is not None and (now - _model_cache_time) < MODEL_CACHE_TTL:
        return _model_cache

    omp = _pi_binary()
    if omp is None:
        return _model_cache or []

    try:
        result = subprocess.run(
            [omp, "--list-models"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return _model_cache or []

    ids: list[str] = []
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0] == "provider":
            continue
        provider, model = parts[0], parts[1]
        ids.append(f"{provider}/{model}")
    _model_cache = ids
    _model_cache_time = now
    return ids


def _is_free(model_id: str) -> bool:
    name = model_id.split("/", 1)[1] if "/" in model_id else model_id
    return name.endswith("-free") or ":free" in name or name == "free"


def free_model_ids(force: bool = False) -> list[str]:
    all_ids = query_provider_models(force=force)
    if not all_ids:
        return list(DEFAULT_MODEL_CHAIN)

    free = [m for m in all_ids if _is_free(m)]

    def sort_key(mid: str) -> tuple[int, int]:
        provider = mid.split("/", 1)[0]
        try:
            pidx = PROVIDER_PREFERENCE.index(provider)
        except ValueError:
            pidx = len(PROVIDER_PREFERENCE)
        return (pidx, all_ids.index(mid))

    free.sort(key=sort_key)

    if LOCAL_FALLBACK not in free:
        free.append(LOCAL_FALLBACK)
    return free


def _model_chain(model: str, limit: int = 0) -> list[str]:
    chain: list[str] = []
    if model:
        chain.append(model)
    for candidate in free_model_ids():
        if candidate not in chain:
            chain.append(candidate)
        if limit and len(chain) >= limit:
            break
    return chain[:limit] if limit and limit > 0 else chain


def _extract_text(ndjson: str) -> str | None:
    """Pull the final assistant text out of the pi `--mode json` event stream."""
    text: list[str] = []
    for line in ndjson.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "message_end":
            content = ev.get("message", {}).get("content", [])
            text = [c.get("text", "") for c in content if c.get("type") == "text" and c.get("text")]
        elif ev.get("type") == "agent_end":
            messages = ev.get("messages", [])
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", [])
                    t = [c.get("text", "") for c in content if c.get("type") == "text" and c.get("text")]
                    if t:
                        text = t
                        break
    if text:
        return "\n".join(text).strip()
    return None


def _detect_error(line: str) -> tuple[bool, str]:
    line_str = line.strip()
    if not line_str:
        return False, ""

    try:
        ev = json.loads(line_str)
        if isinstance(ev, dict):
            ev_type = ev.get("type", "")
            if ev_type == "auto_retry_start":
                err_msg = ev.get("errorMessage") or "auto retry initiated"
                return True, f"auto_retry ({err_msg})"
            if ev_type == "error":
                err_msg = ev.get("error") or ev.get("message") or "error event"
                return True, f"error event ({err_msg})"
            if ev.get("errorMessage"):
                return True, f"errorMessage ({ev.get('errorMessage')})"
            if ev_type == "message_end":
                stop_reason = ev.get("message", {}).get("stopReason", "")
                if stop_reason in ("error", "abort"):
                    return True, f"stopReason={stop_reason}"
            return False, ""
    except (json.JSONDecodeError, ValueError):
        pass

    lower = line_str.lower()
    if "429" in line_str or "rate limit" in lower or "ratelimit" in lower:
        return True, f"rate limit: {line_str[:120]}"
    if "error from provider" in lower:
        return True, f"provider error: {line_str[:120]}"
    if "insufficient_quota" in lower or "quota exceeded" in lower:
        return True, "quota exceeded"
    if "unauthorized" in lower or "authentication error" in lower:
        return True, "auth error"

    return False, ""


class PiLLM:
    """LLM adapter compatible with AgentController.llm interface.

    Expects .complete(prompt: str) -> str returning JSON string with
    {thought, action, selector, value} or similar.
    """

    def __init__(self, model: str = "", max_attempts: int = 0, timeout: int = 300):
        self.model = model
        self.max_attempts = max_attempts
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        """Run pi and return the final response text."""
        omp = _pi_binary()
        if omp is None:
            logger.warning("pi binary not found on PATH")
            return ""

        base_cmd = [omp, "-p", prompt, "--mode", "json"]
        if self.model:
            base_cmd += ["--model", self.model]

        chain = _model_chain(self.model, self.max_attempts)
        total_models = len(chain)

        for i, m in enumerate(chain, 1):
            cmd = base_cmd + ["--model", m]
            logger.info(f"[LLM] Attempt {i}/{total_models} (model: {m})")

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            error_encountered = False
            error_reason = ""
            start_time = time.time()

            while proc.poll() is None:
                if time.time() - start_time > self.timeout + 10:
                    error_encountered = True
                    error_reason = f"timed out after {self.timeout}s"
                    break

                streams = [s for s in (proc.stdout, proc.stderr) if s is not None]
                if not streams:
                    break

                try:
                    ready, _, _ = select.select(streams, [], [], 0.5)
                except (io.UnsupportedOperation, ValueError, TypeError, OSError):
                    ready = streams

                if not ready:
                    continue

                for stream in ready:
                    line = stream.readline()
                    if not line:
                        continue
                    line_str = line.strip()
                    if not line_str:
                        continue

                    if stream == proc.stdout:
                        stdout_lines.append(line_str)
                    else:
                        stderr_lines.append(line_str)

                    is_err, reason = _detect_error(line_str)
                    if is_err:
                        error_encountered = True
                        error_reason = reason
                        break
                sys.stderr.flush()

                if error_encountered:
                    break

            if error_encountered:
                logger.warning(f"[LLM] Attempt {i} error detected ({error_reason}) — cancelling and trying next model")
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=2)
                    except Exception:
                        pass
                continue

            if proc.stdout:
                for line in proc.stdout.read().splitlines():
                    line_str = line.strip()
                    if line_str:
                        stdout_lines.append(line_str)
                        is_err, reason = _detect_error(line_str)
                        if is_err:
                            error_encountered = True
                            error_reason = reason
            if proc.stderr:
                for line in proc.stderr.read().splitlines():
                    line_str = line.strip()
                    if line_str:
                        stderr_lines.append(line_str)
                        is_err, reason = _detect_error(line_str)
                        if is_err:
                            error_encountered = True
                            error_reason = reason

            if error_encountered:
                logger.warning(f"[LLM] Attempt {i} error detected ({error_reason}) — trying next model")
                continue

            if proc.returncode != 0:
                tail = [l for l in stderr_lines if l][-3:]
                logger.warning(f"[LLM] Attempt {i} failed with code {proc.returncode} (model: {m}): {' | '.join(tail) or 'no stderr'}")
                continue

            stdout_data = "\n".join(stdout_lines)
            result = _extract_text(stdout_data)
            if not result:
                logger.warning(f"[LLM] Attempt {i} returned no text (model: {m}) — retrying")
                continue

            logger.info(f"[LLM] Attempt {i} succeeded (model: {m})")
            return result

        logger.error("[LLM] No model produced usable text — giving up")
        return ""


# Singleton instance
_default_llm: PiLLM | None = None


def get_llm(model: str = "", max_attempts: int = 0, timeout: int = 300) -> PiLLM:
    global _default_llm
    if _default_llm is None:
        _default_llm = PiLLM(model=model, max_attempts=max_attempts, timeout=timeout)
    return _default_llm