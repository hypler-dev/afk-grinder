import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.templates import DEFAULT_TEMPLATE, parse_template


class TemplateTests(unittest.TestCase):
    def test_default_template_is_bounded_input_check(self):
        workflow = parse_template(DEFAULT_TEMPLATE)
        self.assertEqual([s.key for s in workflow.steps], ["w", "", "s"])

    def test_click_has_fixed_duration(self):
        workflow = parse_template(json.dumps({"version": 1, "name": "Click", "steps": [
            {"action": "click", "button": "left"}]}))
        self.assertEqual(workflow.steps[0].duration_ms, 80)

    def test_rejects_arbitrary_keys_fields_loops_and_invalid_types(self):
        invalid = [
            {"action": "hold_key", "key": "enter", "duration_ms": 20},
            {"action": "hold_key", "key": ["w"], "duration_ms": 20},
            {"action": "hold_key", "key": "w", "duration_ms": True},
            {"action": "hold_key", "key": "w", "duration_ms": 5001},
            {"action": "wait", "duration_ms": 0},
            {"action": "wait", "duration_ms": float("inf")},
            {"action": "repeat", "count": 100},
            {"action": "text", "value": "secret"},
            {"action": "click", "button": "middle"},
            {"action": "click", "button": "left", "duration_ms": 999},
            {"action": "wait", "duration_ms": 100, "script": "arbitrary"},
        ]
        for step in invalid:
            with self.subTest(step=step), self.assertRaises(ValueError):
                parse_template(json.dumps({"version": 1, "name": "Invalid", "steps": [step]}))

    def test_rejects_total_budget_and_size(self):
        for steps in ([{"action": "wait", "duration_ms": 5000}] * 6,
                      [{"action": "wait", "duration_ms": 1}] * 101, []):
            with self.subTest(steps=len(steps)), self.assertRaises(ValueError):
                parse_template(json.dumps({"version": 1, "name": "Too long", "steps": steps}))
        with self.assertRaises(ValueError):
            parse_template(" " * 65537)

    def test_rejects_malformed_roots_version_and_name(self):
        for value in ("{", "[]", '{"version": true, "name": "x", "steps": []}',
                      '{"version": 1, "name": null, "steps": [{"action":"wait","duration_ms":1}]}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_template(value)
