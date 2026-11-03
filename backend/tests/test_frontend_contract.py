"""Phase 17: static contract check between the frontend and the real OpenAPI schema.

Every API path literal in the frontend (src/api/*.ts and pages/components that call request()/fetch())
must match an operation in the backend, and every in-app link/navigation target must match a <Route>.
This is a static check (no browser): it catches renamed/removed endpoints and dead nav links.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.main import app

FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
pytestmark = pytest.mark.skipif(not FRONT.is_dir(), reason="frontend sources not present")

PREFIX = "/api/v1"


def _openapi():
    ops: dict[str, set[str]] = {}
    for path, item in app.openapi()["paths"].items():
        rel = path[len(PREFIX):] if path.startswith(PREFIX) else path
        ops[rel] = {m.upper() for m in item if m in ("get", "post", "put", "patch", "delete")}
    return ops


def _to_regex(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(path).replace(r"\{", "{").replace(r"\}", "}")) + "$")


def _match(path: str, ops):
    # a literal route beats a parameterised one (e.g. /reports/purge-expired vs /reports/{id})
    hits = [p for p in ops if _to_regex(p).match(path)]
    return sorted(hits, key=lambda p: p.count("{"))


CALL_START = re.compile(r"(?:\brequest(?:<[^()]*?>)?|\brequestText|\bfetch)\(\s*", re.S)


def _read_literal(text: str, i: int):
    """Reads a '...', "..." or `...` literal at text[i] (handling ${...} nesting); returns (value, end) or None."""
    q = text[i] if i < len(text) else ""
    if q not in "'\"`":
        return None
    j, depth, out = i + 1, 0, []
    while j < len(text):
        c = text[j]
        if q == "`" and c == "$" and text[j + 1: j + 2] == "{":
            depth, j = 1, j + 2
            out.append("${")
            while j < len(text) and depth:
                depth += (text[j] == "{") - (text[j] == "}")
                j += 1
            out.append("}")
            continue
        if c == q and depth == 0:
            return "".join(out), j + 1
        out.append(c)
        j += 1
    return None


def _call_args(text: str, i: int) -> str:
    depth, j = 1, i
    while j < len(text) and depth:
        depth += (text[j] in "([{") - (text[j] in ")]}")
        j += 1
    return text[i:j]


def _frontend_calls():
    out = []
    for f in list(FRONT.rglob("*.ts")) + list(FRONT.rglob("*.tsx")):
        text = f.read_text(encoding="utf-8")
        for m in CALL_START.finditer(text):
            lit = _read_literal(text, m.end())
            if lit is None:
                continue
            raw = lit[0]
            raw = raw[len("${API_BASE}"):] if raw.startswith("${API_BASE}") else raw
            if not raw.startswith("/"):
                continue
            path = re.sub(r"\$\{(?:[^{}]|\{[^{}]*\})*\}", "X", raw).split("?")[0]
            path = re.sub(r"(?<=[^/])X$", "", re.sub(r"(?<=[^/])X(?=/|$)", "", path))  # `${qs(...)}` suffixes are query strings
            path = path[len("/api/v1"):] if path.startswith("/api/v1/") else path
            args = _call_args(text, m.end())
            method = re.search(r"method:\s*['\"](GET|POST|PUT|PATCH|DELETE)['\"]", args)
            out.append((f.relative_to(FRONT).as_posix(), raw, path, method.group(1) if method else "GET"))
    return out


def test_every_frontend_api_call_matches_a_backend_operation():
    ops = _openapi()
    calls = _frontend_calls()
    assert len(calls) > 100, "the extractor found too few calls; the regex needs updating"
    bad = []
    for file, raw, path, method in calls:
        if path.rstrip("/") == "" or path == "/X":
            continue  # dynamic prefix helper, resolved at call sites
        hits = _match(path.rstrip("/") or "/", ops)
        if not hits:
            bad.append(f"{file}: {method} {raw} -> no such path")
        elif not any(method in ops[h] for h in hits):
            bad.append(f"{file}: {method} {raw} -> path exists but not for {method} ({[sorted(ops[h]) for h in hits]})")
    assert not bad, "\n".join(bad)


def test_every_navigation_target_has_a_route():
    app_tsx = (FRONT / "App.tsx").read_text(encoding="utf-8")
    routes = [re.sub(r":[A-Za-z]+", "X", m) for m in re.findall(r'<Route path="([^"]+)"', app_tsx)]
    nav = (FRONT / "components/layout/navigation.ts").read_text(encoding="utf-8")
    targets = re.findall(r"\{ to: '([^']+)'", nav)
    assert len(targets) > 50
    def known(t):
        t = t.split("?")[0]
        return any(re.fullmatch(re.escape(r).replace("X", "[^/]+"), t) for r in routes)
    dead = [t for t in targets if not known(t)]
    assert not dead, f"navigation items without a route: {dead}"
    # ...and the reverse: every static page is reachable from the navigation ("/" is the Overview link).
    orphans = [r for r in routes if "X" not in r and r not in ("*", "/login", "/") and r not in targets]
    assert not orphans, f"routes missing from navigation.ts: {orphans}"
    links = set()
    for f in list(FRONT.rglob("*.tsx")):
        for t in re.findall(r"""(?:to=|navigate\()\s*[{(]?\s*[`'"](/[^`'"?]*)""", f.read_text(encoding="utf-8")):
            t = re.sub(r"\$\{[^}]*\}", "X", t)
            links.add((f.name, t.rstrip("/") or "/"))
    dead2 = sorted((f, t) for f, t in links if not known(t))
    assert not dead2, f"links/navigation without a route: {dead2}"


def test_contract_checker_detects_problems():
    ops = _openapi()
    assert _match("/definitely/not/a/route", ops) == []
    assert "POST" not in ops["/reporting/templates"]          # a wrong method is distinguishable from a wrong path
    assert _match("/reporting/reports/purge-expired", ops)[0] == "/reporting/reports/purge-expired"  # literal route wins over {id}
    from collections import Counter

    methods = Counter(m for *_, m in _frontend_calls())
    assert methods["POST"] > 20 and methods["GET"] > 100 and methods["PATCH"] > 3, methods
