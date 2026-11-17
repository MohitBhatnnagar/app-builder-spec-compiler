"""Compile a spec into prompts for an AI app builder.

Builders differ in how much text they accept and in whether they work better from one large prompt
or a sequence of smaller ones. Targets therefore carry only two settings you provide: a style
("single" or "staged") and a character budget. Prompts that exceed the budget are split at
paragraph boundaries rather than truncated, so nothing is silently dropped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Target:
    name: str
    style: str = "staged"        # "single" or "staged"
    max_chars: int = 6000
    preamble: str = ""

    def __post_init__(self):
        if self.style not in ("single", "staged"):
            raise ValueError("style must be 'single' or 'staged'")
        if self.max_chars < 500:
            raise ValueError("max_chars must be at least 500")


def load_targets(path: str | Path) -> dict[str, Target]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: Target(k, **v) for k, v in raw.items() if not k.startswith("_")}


# ---- section builders ----------------------------------------------------------

def overview(spec: dict) -> str:
    a = spec["app"]
    lines = [f"Build a web app called {a['name']}: {a['one_liner']}"]
    if a.get("audience"):
        lines.append(f"Audience: {a['audience']}")
    return "\n".join(lines)


def data_model(spec: dict) -> str:
    ents = spec.get("data", {}).get("entities", [])
    if not ents:
        return ""
    out = ["Data model:"]
    for e in ents:
        fields = ", ".join(f"{f['name']} ({f['type']}{', required' if f.get('required') else ''})" for f in e.get("fields", []))
        out.append(f"- {e['name']}: {fields}")
        for r in e.get("relations", []):
            out.append(f"  - {r.get('kind', 'belongs to')} {r['to']}")
    return "\n".join(out)


def auth_section(spec: dict) -> str:
    a = spec.get("auth", {})
    if a.get("method", "none") == "none":
        return "No sign-in is required."
    roles = "; ".join(f"{r['name']}: {r.get('can', '')}" if isinstance(r, dict) else str(r) for r in a.get("roles", []))
    return f"Authentication: {a['method']}. Roles and permissions: {roles}."


def screens_section(spec: dict) -> str:
    out = ["Screens:"]
    for s in spec["screens"]:
        out.append(f"- {s['name']} ({s['id']}): {s.get('purpose', '')}")
        if s.get("elements"):
            out.append("  Elements: " + "; ".join(s["elements"]))
        if s.get("states"):
            out.append("  States to design: " + ", ".join(s["states"]))
        if s.get("navigation"):
            out.append("  Links to: " + ", ".join(s["navigation"]))
    return "\n".join(out)


def rules_section(spec: dict) -> str:
    rules = spec.get("rules", [])
    return "Business rules:\n" + "\n".join(f"- {r}" for r in rules) if rules else ""


def acceptance_section(spec: dict) -> str:
    out = ["Acceptance criteria (the app is done only when all of these hold):"]
    for a in spec.get("acceptance", []):
        out.append(f"- {a.get('id', '')}: Given {a['given']}, when {a['when']}, then {a['then']}.")
    return "\n".join(out)


# ---- compilation ---------------------------------------------------------------

def split_to_budget(text: str, budget: int) -> list[str]:
    """Split on blank lines, then on lines, so no chunk exceeds the budget and nothing is cut mid-line.
    A single line longer than the budget is rejected: it cannot be split without losing meaning."""
    if len(text) <= budget:
        return [text]
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        for piece in ([para] if len(para) <= budget else para.split("\n")):
            if len(piece) > budget:
                raise ValueError(f"a single line is {len(piece)} characters, over the {budget} budget; shorten it")
            if cur and len(cur) + len(piece) + 2 > budget:
                chunks.append(cur)
                cur = ""
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        chunks.append(cur)
    return chunks


def compile_prompts(spec: dict, target: Target) -> list[dict]:
    """Return [{"stage": str, "prompt": str}] in the order they should be sent."""
    sections = [("scaffold", [overview(spec), data_model(spec), auth_section(spec)]),
                ("screens", [screens_section(spec)]),
                ("rules and acceptance", [rules_section(spec), acceptance_section(spec)])]
    pre = (target.preamble + "\n\n") if target.preamble else ""
    if target.style == "single":
        text = pre + "\n\n".join(p for _, parts in sections for p in parts if p)
        stages = [("full spec", text)]
    else:
        stages = []
        for i, (name, parts) in enumerate(sections, start=1):
            body = "\n\n".join(p for p in parts if p)
            lead = pre if i == 1 else f"Continue building the same app (step {i} of {len(sections)}). Keep everything from earlier steps.\n\n"
            stages.append((name, lead + body))
    out = []
    for name, text in stages:
        parts = split_to_budget(text, target.max_chars)
        for j, chunk in enumerate(parts, start=1):
            label = name if len(parts) == 1 else f"{name} (part {j} of {len(parts)})"
            out.append({"stage": label, "prompt": chunk})
    return out


def qa_checklist(spec: dict) -> str:
    """Turn acceptance criteria into a manual test checklist to run on the generated app."""
    lines = [f"# QA checklist: {spec['app']['name']}", ""]
    for a in spec.get("acceptance", []):
        lines += [f"- [ ] **{a.get('id', '')}** Given {a['given']}", f"  - When {a['when']}", f"  - Then {a['then']}"]
    lines += ["", "## Every screen, every state", ""]
    for s in spec["screens"]:
        for st in s.get("states", []):
            lines.append(f"- [ ] {s['name']}: {st} state looks and behaves correctly")
    return "\n".join(lines) + "\n"
