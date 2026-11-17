"""Product spec validation and linting for prompt-to-app builders.

Prompt-to-app tools (Bolt, Rocket, Hercules, Lovable, Replit's agent and similar) build what the
prompt says, including its gaps. Vague words, missing screen states and undefined references turn
into guesses by the builder. This module catches them in the spec, before any credits are spent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FIELD_TYPES = {"text", "number", "boolean", "date", "datetime", "email", "url", "enum", "json", "image"}
REQUIRED_STATES = ("empty", "loading", "error")
AUTH_METHODS = {"none", "email_password", "magic_link", "oauth"}
VAGUE = re.compile(r"\b(etc\.?|and so on|user[- ]friendly|intuitive|seamless(ly)?|modern|sleek|fast|"
                   r"as needed|appropriate(ly)?|TBD|TODO|some kind of|various|robust|simple|easy to use)\b", re.I)
PII_FIELDS = re.compile(r"(email|phone|mobile|dob|birth|address|passport|ssn|national_id|salary)", re.I)
PRIVACY = re.compile(r"(privacy|delete|erase|retention|consent|gdpr|anonymi[sz]e)", re.I)


class SpecError(ValueError):
    pass


def load(path: str | Path) -> dict:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(spec)
    return spec


def validate(spec: dict) -> None:
    """Structural validation: raises SpecError. Quality problems are lint findings instead."""
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    app = spec.get("app", {})
    if not app.get("name") or not app.get("one_liner"):
        raise SpecError("app.name and app.one_liner are required")
    screens = spec.get("screens")
    if not isinstance(screens, list) or not screens:
        raise SpecError("at least one screen is required")
    ids = [s.get("id") for s in screens]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise SpecError("every screen needs a unique id")
    for ent in spec.get("data", {}).get("entities", []):
        if not ent.get("name"):
            raise SpecError("every entity needs a name")
        for f in ent.get("fields", []):
            if f.get("type") not in FIELD_TYPES:
                raise SpecError(f"{ent['name']}.{f.get('name')}: type must be one of {sorted(FIELD_TYPES)}")
    if spec.get("auth", {}).get("method", "none") not in AUTH_METHODS:
        raise SpecError(f"auth.method must be one of {sorted(AUTH_METHODS)}")


def _strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def lint(spec: dict) -> list[dict]:
    """Findings as {"level": "error"|"warning", "code": str, "message": str}."""
    out: list[dict] = []

    def add(level, code, msg):
        out.append({"level": level, "code": code, "message": msg})

    for text in _strings({k: v for k, v in spec.items() if k not in ("acceptance",)}):
        m = VAGUE.search(text)
        if m:
            add("warning", "vague-wording", f"vague wording {m.group(0)!r} in: {text[:70]!r}. State it concretely")

    screen_ids = {s["id"] for s in spec["screens"]}
    for s in spec["screens"]:
        states = set(s.get("states", []))
        for st in REQUIRED_STATES:
            if st not in states:
                add("warning", "missing-state", f"screen {s['id']!r} does not define its {st!r} state; the builder will invent one")
        for target in s.get("navigation", []):
            if target not in screen_ids:
                add("error", "unknown-screen", f"screen {s['id']!r} navigates to undefined screen {target!r}")
        if not s.get("purpose"):
            add("warning", "no-purpose", f"screen {s['id']!r} has no purpose statement")

    entities = {e["name"] for e in spec.get("data", {}).get("entities", [])}
    for e in spec.get("data", {}).get("entities", []):
        if not e.get("fields"):
            add("warning", "empty-entity", f"entity {e['name']!r} has no fields")
        for rel in e.get("relations", []):
            if rel.get("to") not in entities:
                add("error", "unknown-entity", f"{e['name']!r} relates to undefined entity {rel.get('to')!r}")
        pii = [f["name"] for f in e.get("fields", []) if PII_FIELDS.search(f.get("name", ""))]
        if pii and not any(PRIVACY.search(r) for r in spec.get("rules", [])):
            add("warning", "pii-without-privacy-rule", f"{e['name']!r} stores {pii} but no rule covers privacy, deletion or retention")

    auth = spec.get("auth", {})
    if auth.get("method", "none") == "none" and auth.get("roles"):
        add("error", "roles-without-auth", "roles are defined but auth.method is 'none'")
    if auth.get("method", "none") != "none" and not auth.get("roles"):
        add("warning", "no-roles", "authentication is enabled but no roles define who can do what")

    acceptance = spec.get("acceptance", [])
    if not acceptance:
        add("error", "no-acceptance", "no acceptance criteria: nothing defines done")
    covered = " ".join(_strings(acceptance)).lower()
    for s in spec["screens"]:
        if s["id"].lower() not in covered and s.get("name", "").lower() not in covered:
            add("warning", "screen-without-acceptance", f"no acceptance criterion mentions screen {s['id']!r}")
    for a in acceptance:
        for part in ("given", "when", "then"):
            if not a.get(part):
                add("error", "incomplete-criterion", f"criterion {a.get('id', '?')!r} is missing '{part}'")
    return out
