from __future__ import annotations

import argparse
import json
import sys

from .compile import compile_prompts, load_targets, qa_checklist
from .spec import SpecError, lint, load


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="specc", description="Lint a product spec and compile it into builder prompts")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lint").add_argument("spec")
    c = sub.add_parser("compile")
    c.add_argument("spec")
    c.add_argument("--targets", required=True)
    c.add_argument("--target", required=True)
    sub.add_parser("qa").add_argument("spec")
    a = p.parse_args(argv)
    try:
        spec = load(a.spec)
        if a.cmd == "lint":
            findings = lint(spec)
            for f in findings:
                print(f"{f['level']:7} {f['code']:26} {f['message']}")
            return 1 if any(f["level"] == "error" for f in findings) else 0
        if a.cmd == "qa":
            print(qa_checklist(spec))
            return 0
        targets = load_targets(a.targets)
        if a.target not in targets:
            raise SpecError(f"unknown target {a.target!r}; available: {sorted(targets)}")
        errors = [f for f in lint(spec) if f["level"] == "error"]
        if errors:
            raise SpecError("spec has errors; run 'specc lint' first (" + errors[0]["message"] + ")")
        for i, pr in enumerate(compile_prompts(spec, targets[a.target]), start=1):
            print(f"===== Prompt {i}: {pr['stage']} ({len(pr['prompt'])} chars) =====\n{pr['prompt']}\n")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
