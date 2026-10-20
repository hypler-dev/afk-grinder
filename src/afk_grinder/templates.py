"""Strict declarative workflows with a short, fixed execution budget."""

import json

from .models import BUTTONS, KEYS, Step, Workflow

COUNTDOWN_SECONDS = 3.0
MAX_STEPS = 100
MAX_ACTION_MS = 5000
MAX_WORKFLOW_MS = 27000
CLICK_MS = 80
MAX_TEMPLATE_BYTES = 65536

DEFAULT_TEMPLATE = '''{
  "version": 1,
  "name": "Adopt Me - supervised input check",
  "steps": [
    {"action": "hold_key", "key": "w", "duration_ms": 250},
    {"action": "wait", "duration_ms": 500},
    {"action": "hold_key", "key": "s", "duration_ms": 250}
  ]
}'''


def validate_workflow(workflow: Workflow) -> None:
    if not isinstance(workflow, Workflow):
        raise ValueError("Expected a workflow.")
    if (not isinstance(workflow.name, str) or not 1 <= len(workflow.name) <= 80
            or any(ord(c) < 32 for c in workflow.name)):
        raise ValueError("Workflow name must contain 1-80 printable characters.")
    if not isinstance(workflow.steps, tuple) or not 1 <= len(workflow.steps) <= MAX_STEPS:
        raise ValueError("A workflow must have 1-100 steps.")
    total = 0
    for index, step in enumerate(workflow.steps, 1):
        if not isinstance(step, Step) or step.action not in {"hold_key", "wait", "click"}:
            raise ValueError(f"Step {index}: unsupported action.")
        if type(step.duration_ms) is not int or not 1 <= step.duration_ms <= MAX_ACTION_MS:
            raise ValueError(f"Step {index}: duration_ms must be an integer from 1 to 5000.")
        if step.action == "hold_key":
            if step.key not in KEYS or step.button:
                raise ValueError(f"Step {index}: use a movement key, e, space, or an arrow key.")
        elif step.action == "click":
            if step.button not in BUTTONS or step.key or step.duration_ms != CLICK_MS:
                raise ValueError(f"Step {index}: clicks require left/right button and fixed 80 ms duration.")
        elif step.key or step.button:
            raise ValueError(f"Step {index}: wait cannot include a key or button.")
        total += step.duration_ms
    if total > MAX_WORKFLOW_MS:
        raise ValueError("Actions exceed 27 seconds; including countdown, runs are limited to 30 seconds.")


def parse_template(source: str) -> Workflow:
    if len(source.encode("utf-8")) > MAX_TEMPLATE_BYTES:
        raise ValueError("Template exceeds 64 KiB.")
    try:
        data = json.loads(source)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Template must be valid JSON.") from exc
    if not isinstance(data, dict) or set(data) != {"version", "name", "steps"}:
        raise ValueError("Template requires exactly version, name, and steps.")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Only template version 1 is supported.")
    if not isinstance(data["steps"], list) or not 1 <= len(data["steps"]) <= MAX_STEPS:
        raise ValueError("A workflow must have 1-100 steps.")
    steps = []
    for index, item in enumerate(data["steps"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"Step {index}: expected an action object.")
        action = item.get("action")
        required = {"hold_key": {"action", "key", "duration_ms"},
                    "wait": {"action", "duration_ms"}, "click": {"action", "button"}}
        if not isinstance(action, str) or action not in required or set(item) != required[action]:
            raise ValueError(f"Step {index}: unsupported action or fields.")
        if action == "hold_key" and not isinstance(item["key"], str):
            raise ValueError(f"Step {index}: key must be text.")
        if action == "click" and not isinstance(item["button"], str):
            raise ValueError(f"Step {index}: button must be text.")
        steps.append(Step(action, CLICK_MS if action == "click" else item["duration_ms"],
                          item.get("key", ""), item.get("button", "")))
    workflow = Workflow(data["name"], tuple(steps))
    validate_workflow(workflow)
    return workflow
