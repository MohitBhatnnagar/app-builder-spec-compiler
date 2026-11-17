# app-builder-spec-compiler

AI app builders (Bolt, Rocket, Hercules, Lovable, Replit's agent and similar) build what your prompt says, **including its gaps**. A vague word, a screen with no error state or a link to a screen that does not exist becomes a guess by the builder, and each guess costs credits and rework.

This tool treats the product spec as the real artifact: a structured JSON spec that is **linted** for ambiguity and gaps, then **compiled** into a sequence of prompts sized for a chosen builder, plus a **QA checklist** to verify the generated app against the acceptance criteria.

Standard library only. 36 tests.

```bash
pip install -e .
specc lint examples/spec.json                      # exit 1 on errors
specc compile examples/spec.json --targets examples/targets.json --target bolt
specc qa examples/spec.json                        # manual test checklist
python -m unittest discover -s tests -v
```

## What the linter catches

| Finding | Level | Why it matters |
|---|---|---|
| Vague wording ("user-friendly", "modern", "etc.", "TBD", "as needed", "fast") | warning | The builder fills the gap with its own taste |
| A screen without `empty`, `loading` or `error` states | warning | Generated apps usually handle only the happy path |
| Navigation to an undefined screen; a relation to an undefined entity | error | Produces broken links or schema |
| Roles defined but auth `none`; auth on but no roles | error / warning | A contradiction or an unspecified permission model |
| Personal-data fields (email, phone, birth date...) with no privacy or deletion rule | warning | Privacy gets skipped unless someone asked for it |
| No acceptance criteria, or a criterion missing given, when or then | error | Nothing defines done |
| A screen no acceptance criterion mentions | warning | That screen will not be tested |

`compile` refuses to run on a spec with errors.

## Compilation

A target has two settings you provide: a **style** (`single` prompt or `staged` sequence) and a **character budget**. The staged style sends scaffold and data model first, then screens, then rules and acceptance criteria, each later step telling the builder to keep everything from earlier steps.

If a stage exceeds the budget it is split at paragraph and line boundaries. **Nothing is truncated**: a test checks that the split content reassembles exactly, and a line too long to split is rejected with an error rather than cut.

The sample `targets.json` uses **illustrative** limits for five named builders. Each builder's real input limit and best prompting style differ and change, so measure them for your builder and edit the file. This repo does not call any builder's API and has not been tested against the builders themselves, only against its own output.

## Design decisions

1. **Spec first, prompt second.** The prompt is a compiled artifact. When the builder misunderstands, you fix the spec and recompile instead of tweaking prose.
2. **Gaps are cheaper to fix before generation.** Every lint finding is a question the builder would otherwise answer silently.
3. **Acceptance criteria are required.** They become both part of the prompt and the QA checklist, so the same sentences define the request and verify the result.
4. **Targets are configuration, not code.** Builders change quickly; their limits live in a data file.
5. **Honest about the privacy rule.** The lint only checks that *some* rule mentions privacy, retention or deletion. It cannot judge whether the rule is adequate.

## Limits

- Wording checks are a word list, so they miss vague phrasing that avoids those words.
- No validation of the generated app. The QA checklist is manual; browser-test generation would be the next step.
- JSON, not a friendlier format. A form or YAML front end could sit on top.

Related: [`coding-agent-config`](https://github.com/MohitBhatnnagar/coding-agent-config) (the same single-source idea for coding agents), [`automation-platform-toolkit`](https://github.com/MohitBhatnnagar/automation-platform-toolkit), [`persona-studio`](https://github.com/MohitBhatnnagar/persona-studio) and [`horaskope`](https://github.com/MohitBhatnnagar/horaskope) (products built this way).

## License

MIT
