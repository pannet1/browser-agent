from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.features.skills import manager as mgr
from app.features.skills.router import route
from app.features.skills.memory import append_trace, load_traces
from app.features.terminal.parser import dispatch


@pytest.fixture(autouse=True)
def tmp_skills(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(mgr, "SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setattr(mgr, "DATA_ROOT", tmp_path)
    import app.features.skills.memory as mem
    monkeypatch.setattr(mem, "_skill_dir", lambda sid: tmp_path / "skills" / sid)
    monkeypatch.setattr(mem, "_shared_dir", lambda d: tmp_path / "skills" / "_shared" / d)
    return tmp_path


def test_create_and_list_skill(tmp_skills: Path) -> None:
    meta = mgr.create_skill("hacker news", "news.ycombinator.com")
    assert meta["target_domain"] == "news.ycombinator.com"
    assert (tmp_skills / "skills" / meta["id"] / "meta.json").exists()
    skills = mgr.list_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "hacker news"


def test_domain_shared_storage(tmp_skills: Path) -> None:
    m1 = mgr.create_skill("facebook messages", "facebook.com")
    m2 = mgr.create_skill("facebook marketplace", "facebook.com")
    p1 = mgr.get_shared_paths("facebook.com")
    assert p1["storage"].parent.exists()
    assert (tmp_skills / "skills" / m1["id"]).exists()
    assert (tmp_skills / "skills" / m2["id"]).exists()


def test_router_browse_hacker_news(tmp_skills: Path) -> None:
    res = route("browse hacker news")
    assert res["target_domain"] == "news.ycombinator.com"
    assert res["skill_name"] == "hacker news"
    assert res["is_new"] is True
    res2 = route("browse hacker news")
    assert res2["is_new"] is False
    assert res2["skill_id"] == res["skill_id"]


def test_router_facebook_shared_domain(tmp_skills: Path) -> None:
    r1 = route("check facebook messages")
    assert r1["skill_name"] == "facebook messages"
    r2 = route("check facebook marketplace")
    assert r2["is_new"] is True
    assert r2["target_domain"] == "facebook.com"
    assert r2["skill_id"] != r1["skill_id"]


def test_memory_traces(tmp_skills: Path) -> None:
    meta = mgr.create_skill("test", "example.com")
    append_trace(meta["id"], "example.com", {"thought": "t1", "action": "click", "result": "ok"})
    traces = load_traces(meta["id"], "example.com")
    assert any(t["thought"] == "t1" for t in traces)
    shared = load_traces("other", "example.com")
    assert any(t["thought"] == "t1" for t in shared)


def test_dispatch_via_terminal_parser(tmp_skills: Path) -> None:
    existing: list[dict[str, str]] = []
    r = dispatch("browse hacker news", existing)
    assert r["target_domain"] == "news.ycombinator.com"
    assert r["skill_name"] == "hacker news"
