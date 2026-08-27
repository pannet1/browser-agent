from __future__ import annotations

from typing import Any

from app.core.logger import logging_func

logger = logging_func(__name__)

SYSTEM_TEMPLATE: str = """You are a browser agent. Instruction: {instruction}
Skill: {skill_name} ({target_domain})
Current URL: {url}
AX tree: {ax_tree}
Recent traces:
{traces}
Respond with JSON: {{\"thought\":..., \"action\":..., \"selector\":..., \"value\":...}}
Allowed actions: navigate, click, type, press, wait, extract, auto_login
"""

TRACE_FEEDBACK_TEMPLATE: str = """Previous attempt failed: {error}
Fallback selectors: {fallbacks}
Correction hint: {correction}
"""


def render_prompt(
    instruction: str,
    skill_name: str,
    target_domain: str,
    url: str,
    ax_tree: str,
    traces: list[dict[str, Any]] | None = None,
) -> str:
    trace_block = ""
    if traces:
        for t in traces[-3:]:
            trace_block += f"- {t.get('thought','')} -> {t.get('action','')} = {t.get('result','')}\n"
            if t.get("correction"):
                trace_block += f"  correction: {t['correction']}\n"
    else:
        trace_block = "(no prior traces)"
    prompt = SYSTEM_TEMPLATE.format(
        instruction=instruction,
        skill_name=skill_name,
        target_domain=target_domain,
        url=url,
        ax_tree=ax_tree[:4000],
        traces=trace_block,
    )
    logger.info(f"rendered prompt for {skill_name}")
    return prompt


def render_healer_prompt(error: str, fallbacks: list[str], correction: str) -> str:
    return TRACE_FEEDBACK_TEMPLATE.format(error=error, fallbacks=", ".join(fallbacks), correction=correction)
