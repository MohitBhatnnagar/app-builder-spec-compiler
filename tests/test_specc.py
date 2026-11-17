import copy
import json
import os
import tempfile
import unittest

from specc import SpecError, Target, compile_prompts, lint, load, load_targets, qa_checklist, split_to_budget, validate
from specc.cli import main

EX = os.path.join(os.path.dirname(__file__), "..", "examples")
SPEC, TARGETS = os.path.join(EX, "spec.json"), os.path.join(EX, "targets.json")


def spec():
    return copy.deepcopy(load(SPEC))


def codes(s):
    return [f["code"] for f in lint(s)]


class ValidationTests(unittest.TestCase):
    def test_example_loads_and_has_no_lint_errors(self):
        self.assertFalse([f for f in lint(spec()) if f["level"] == "error"])

    def test_required_app_fields(self):
        s = spec()
        s["app"]["one_liner"] = ""
        with self.assertRaises(SpecError):
            validate(s)

    def test_needs_screens_with_unique_ids(self):
        s = spec()
        s["screens"] = []
        with self.assertRaises(SpecError):
            validate(s)
        s = spec()
        s["screens"][1]["id"] = "dashboard"
        with self.assertRaises(SpecError):
            validate(s)

    def test_field_types_checked(self):
        s = spec()
        s["data"]["entities"][0]["fields"][0]["type"] = "varchar"
        with self.assertRaises(SpecError):
            validate(s)

    def test_auth_method_checked(self):
        s = spec()
        s["auth"]["method"] = "telepathy"
        with self.assertRaises(SpecError):
            validate(s)

    def test_not_an_object(self):
        with self.assertRaises(SpecError):
            validate([])


class LintTests(unittest.TestCase):
    def test_vague_wording_is_flagged_in_any_field(self):
        for phrase in ("a modern, user-friendly look", "fast and intuitive", "buttons etc.", "TBD", "as needed"):
            s = spec()
            s["screens"][0]["purpose"] = phrase
            self.assertIn("vague-wording", codes(s), phrase)

    def test_no_false_positive_on_clean_spec(self):
        self.assertNotIn("vague-wording", codes(spec()))

    def test_missing_states(self):
        s = spec()
        s["screens"][0]["states"] = ["success"]
        found = [f["message"] for f in lint(s) if f["code"] == "missing-state"]
        self.assertEqual(len(found), 3)

    def test_unknown_screen_navigation(self):
        s = spec()
        s["screens"][0]["navigation"].append("settings")
        self.assertIn("unknown-screen", codes(s))

    def test_unknown_entity_relation(self):
        s = spec()
        s["data"]["entities"][0]["relations"][0]["to"] = "Ghost"
        self.assertIn("unknown-entity", codes(s))

    def test_roles_without_auth(self):
        s = spec()
        s["auth"]["method"] = "none"
        self.assertIn("roles-without-auth", codes(s))

    def test_auth_without_roles(self):
        s = spec()
        s["auth"]["roles"] = []
        self.assertIn("no-roles", codes(s))

    def test_pii_requires_a_privacy_rule(self):
        s = spec()
        s["rules"] = ["Quality is passed over total."]
        self.assertIn("pii-without-privacy-rule", codes(s))

    def test_pii_with_privacy_rule_is_fine(self):
        self.assertNotIn("pii-without-privacy-rule", codes(spec()))

    def test_acceptance_is_required_and_complete(self):
        s = spec()
        s["acceptance"] = []
        self.assertIn("no-acceptance", codes(s))
        s = spec()
        del s["acceptance"][0]["then"]
        self.assertIn("incomplete-criterion", codes(s))

    def test_screen_without_acceptance_coverage(self):
        s = spec()
        s["screens"].append({"id": "settings", "name": "Settings", "purpose": "Change preferences.",
                             "states": ["empty", "loading", "error"], "navigation": []})
        self.assertIn("screen-without-acceptance", codes(s))

    def test_empty_entity_and_missing_purpose(self):
        s = spec()
        s["data"]["entities"].append({"name": "Empty", "fields": []})
        s["screens"][0]["purpose"] = ""
        self.assertTrue({"empty-entity", "no-purpose"} <= set(codes(s)))


class BudgetTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(split_to_budget("hello", 500), ["hello"])

    def test_splits_on_paragraphs_without_loss(self):
        text = "\n\n".join(f"Paragraph number {i} " + "x" * 100 for i in range(10))
        chunks = split_to_budget(text, 500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertEqual("\n\n".join(chunks), text)

    def test_splits_a_long_paragraph_on_line_boundaries(self):
        para = "\n".join(f"- line {i} " + "y" * 60 for i in range(30))
        chunks = split_to_budget(para, 500)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertEqual(sum(c.count("- line") for c in chunks), 30)

    def test_unsplittable_line_is_rejected_not_truncated(self):
        with self.assertRaises(ValueError):
            split_to_budget("z" * 2000 + "\n\nshort", 500)


class CompileTests(unittest.TestCase):
    def test_staged_has_three_ordered_stages(self):
        out = compile_prompts(spec(), Target("t", "staged", 6000))
        self.assertEqual([p["stage"] for p in out], ["scaffold", "screens", "rules and acceptance"])
        self.assertIn("Quality Board", out[0]["prompt"])
        self.assertIn("Data model", out[0]["prompt"])
        self.assertIn("Authentication: email_password", out[0]["prompt"])
        self.assertIn("Defect log", out[1]["prompt"])
        self.assertIn("AC1", out[2]["prompt"])

    def test_later_stages_tell_the_builder_to_keep_earlier_work(self):
        out = compile_prompts(spec(), Target("t", "staged", 6000))
        self.assertIn("Keep everything from earlier steps", out[1]["prompt"])
        self.assertIn("step 3 of 3", out[2]["prompt"])

    def test_single_is_one_prompt_with_everything(self):
        out = compile_prompts(spec(), Target("t", "single", 20000))
        self.assertEqual(len(out), 1)
        for needle in ("Quality Board", "Defect log", "Business rules", "Acceptance criteria"):
            self.assertIn(needle, out[0]["prompt"])

    def test_small_budget_splits_stages_and_never_exceeds_it(self):
        out = compile_prompts(spec(), Target("t", "staged", 600))
        self.assertGreater(len(out), 3)
        self.assertTrue(all(len(p["prompt"]) <= 600 for p in out))
        self.assertTrue(any("part 1 of" in p["stage"] for p in out))

    def test_no_content_is_lost_when_split(self):
        big = compile_prompts(spec(), Target("t", "single", 20000))[0]["prompt"]
        small = "".join(p["prompt"] for p in compile_prompts(spec(), Target("t", "single", 700)))
        for needle in ("AC1", "AC2", "AC3", "Reviewer calibration", "quality percentage card"):
            self.assertIn(needle, small)
            self.assertIn(needle, big)

    def test_preamble_goes_first_only(self):
        out = compile_prompts(spec(), Target("t", "staged", 6000, preamble="Use React."))
        self.assertTrue(out[0]["prompt"].startswith("Use React."))
        self.assertNotIn("Use React.", out[1]["prompt"])

    def test_no_auth_spec(self):
        s = spec()
        s["auth"] = {"method": "none"}
        self.assertIn("No sign-in is required", compile_prompts(s, Target("t", "single", 20000))[0]["prompt"])

    def test_deterministic(self):
        t = Target("t", "staged", 1000)
        self.assertEqual(compile_prompts(spec(), t), compile_prompts(spec(), t))

    def test_target_validation(self):
        with self.assertRaises(ValueError):
            Target("t", "weird", 1000)
        with self.assertRaises(ValueError):
            Target("t", "single", 100)

    def test_targets_file_loads_and_skips_notes(self):
        t = load_targets(TARGETS)
        self.assertEqual(set(t), {"bolt", "rocket", "hercules", "lovable", "replit"})

    def test_qa_checklist_covers_criteria_and_every_screen_state(self):
        q = qa_checklist(spec())
        self.assertEqual(q.count("**AC"), 3)
        self.assertEqual(q.count("state looks and behaves correctly"), 12)


class CliTests(unittest.TestCase):
    def test_lint_compile_qa(self):
        self.assertEqual(main(["lint", SPEC]), 0)
        self.assertEqual(main(["compile", SPEC, "--targets", TARGETS, "--target", "bolt"]), 0)
        self.assertEqual(main(["qa", SPEC]), 0)

    def test_unknown_target(self):
        self.assertEqual(main(["compile", SPEC, "--targets", TARGETS, "--target", "nope"]), 2)

    def test_compile_refuses_a_spec_with_errors(self):
        s = spec()
        s["screens"][0]["navigation"].append("ghost")
        p = os.path.join(tempfile.mkdtemp(), "s.json")
        json.dump(s, open(p, "w"))
        self.assertEqual(main(["compile", p, "--targets", TARGETS, "--target", "bolt"]), 2)
        self.assertEqual(main(["lint", p]), 1)


if __name__ == "__main__":
    unittest.main()
