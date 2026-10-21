"""Local authoring privacy, merge, process and synthetic loopback checks."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image, PngImagePlugin

from afk_grinder import local_authoring as author
from afk_grinder.training_packet import parse_training_packet, _canonical_packet_json
from tests.test_training_packet import payload


MODEL = "fixture-vlm:synthetic-v1"
DIGEST = "a" * 64
TRAIN = "gameplay-001"


def receipt():
    return {"name": MODEL, "digest": DIGEST, "runtime_version": "0.40.6",
            "model_size_bytes": 1024, "cloud_disabled": True, "vision": True,
            "digest_checked_before_after": True}


def proposal():
    return {"states": [], "labels": [{"example_id": TRAIN, "state_id": "gameplay"}],
            "demonstrations": []}


class LocalAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "examples").mkdir()
        raw = payload()
        raw["reference_size"] = [16, 12]
        raw["demonstrations"] = []
        for index, item in enumerate(raw["examples"]):
            image = Image.new("RGB", (16, 12), (index * 60, 40, 100))
            path = self.root / "examples" / f"{item['id']}.png"
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("private-source-metadata", "not-for-model-context")
            image.save(path, pnginfo=metadata)
            image.close()
            item.update(path=f"examples/{item['id']}.png", width=16, height=12,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), origin="synthetic")
        self.packet = parse_training_packet(json.dumps(raw))
        self.packet_path = self.root / "training.json"
        self.packet_path.write_text(_canonical_packet_json(self.packet))
        self.calls = []

    def invoke(self, response=None):
        reply = json.dumps(proposal() if response is None else response)
        with mock.patch("afk_grinder.local_model_transport.generate_local",
                        return_value=(reply, receipt())) as generate:
            report = author.author_examples(self.packet, self.root, MODEL, DIGEST,
                                            (TRAIN,), consent=True)
        return report, generate

    def test_consent_and_selection_fail_before_read_or_network(self):
        with mock.patch.object(author, "_load_packet") as load:
            with self.assertRaisesRegex(author.AuthoringError, "consent_required"):
                author.run_authoring(self.packet_path, self.root, MODEL, DIGEST, (TRAIN,))
            load.assert_not_called()
        for selected in ((), (TRAIN, TRAIN), ("reward-001",), ("gameplay-002",), ("missing",)):
            with self.subTest(selected=selected):
                with self.assertRaisesRegex(author.AuthoringError, "selection_invalid"):
                    author._select(self.packet, selected)
        for port in (True, 0, 1023, 65536):
            with self.subTest(port=port):
                with self.assertRaisesRegex(author.AuthoringError, "model_invalid"):
                    author._profile(MODEL, DIGEST, port)

    def test_only_selected_train_images_are_reencoded_without_source_metadata(self):
        report, generate = self.invoke()
        args, kwargs = generate.call_args
        self.assertEqual(len(args[2]), 1)
        self.assertEqual(args[0].name, MODEL)
        for example in self.packet.examples:
            self.assertNotIn(example.path, args[1])
            self.assertNotIn(example.sha256, args[1])
        self.assertNotIn("reward-001", args[1])
        self.assertNotIn("gameplay-002", args[1])
        image_bytes = base64.b64decode(args[2][0], validate=True)
        self.assertNotIn(b"not-for-model-context", image_bytes)
        with Image.open(BytesIO(image_bytes)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (16, 12))
        self.assertGreater(kwargs["deadline"], 0)
        self.assertEqual(report["status"] if "status" in report else None, "draft")
        self.assertTrue(all(report[key] is False for key in author._FLAGS))
        original = json.loads(_canonical_packet_json(self.packet))
        self.assertEqual(report["packet"], original)
        self.assertEqual(report["selected_examples"], [TRAIN])

    def test_new_state_and_semantic_request_remain_draft_and_preserve_other_examples(self):
        proposed = proposal()
        proposed["states"] = [{"id": "sleepy-pet", "kind": "gameplay",
                               "description": "A sleepy pet need is visible."}]
        proposed["labels"][0]["state_id"] = "sleepy-pet"
        proposed["demonstrations"] = [{"id": "sleep-review", "from_state": "gameplay",
                                      "to_state": "sleepy-pet", "capability_request": "review-sleep",
                                      "example_ids": [TRAIN], "max_duration_ms": 1000, "retry_limit": 0}]
        report, _ = self.invoke(proposed)
        result = parse_training_packet(json.dumps(report["packet"]))
        self.assertEqual(result.examples[0].state_id, "sleepy-pet")
        self.assertEqual(result.examples[1:], self.packet.examples[1:])
        self.assertEqual(result.states[:len(self.packet.states)], self.packet.states)
        self.assertEqual(result.status, "draft")
        self.assertFalse(report["runtime_pack"])
        self.assertFalse(report["approved"])

    def test_rejects_unselected_existing_state_unsafe_capability_and_extra_fields(self):
        cases = []
        unknown = proposal()
        unknown["approved"] = True
        cases.append(unknown)
        existing = proposal()
        existing["states"] = [{"id": "gameplay", "kind": "gameplay", "description": "Changed"}]
        cases.append(existing)
        unselected = proposal()
        unselected["labels"][0]["example_id"] = "gameplay-002"
        cases.append(unselected)
        duplicate = proposal()
        duplicate["labels"].append(deepcopy(duplicate["labels"][0]))
        cases.append(duplicate)
        unsafe = proposal()
        unsafe["demonstrations"] = [{"id": "raw-action", "from_state": "gameplay",
                                     "to_state": "gameplay", "capability_request": "click-button",
                                     "example_ids": [TRAIN], "max_duration_ms": 1000, "retry_limit": 0}]
        cases.append(unsafe)
        held_out = deepcopy(unsafe)
        held_out["demonstrations"][0]["capability_request"] = "review-sleep"
        held_out["demonstrations"][0]["example_ids"] = ["gameplay-002"]
        cases.append(held_out)
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaisesRegex(author.AuthoringError, "proposal_invalid"):
                    self.invoke(value)

    def test_cannot_downgrade_selected_transaction_label(self):
        raw = json.loads(_canonical_packet_json(self.packet))
        raw["examples"][0]["state_id"] = "trade-window"
        self.packet = parse_training_packet(json.dumps(raw))
        with self.assertRaisesRegex(author.AuthoringError, "proposal_invalid"):
            self.invoke()

    def test_worker_result_is_bound_to_original_metadata_and_strict_types(self):
        report, _ = self.invoke()
        valid = {"ok": True, "report": report}
        self.assertEqual(author._bind_report(valid, self.packet, MODEL, DIGEST, (TRAIN,)), report)
        mutations = []
        for field, value in (("approved", True), ("dataset_sha256", "0" * 64),
                             ("selected_examples", ["gameplay-002"])):
            changed = deepcopy(valid)
            changed["report"][field] = value
            mutations.append(changed)
        changed = deepcopy(valid)
        changed["report"]["packet"]["examples"][1]["state_id"] = "gameplay"
        mutations.append(changed)
        changed = deepcopy(valid)
        changed["report"]["packet"]["schema_version"] = True
        mutations.append(changed)
        changed = deepcopy(valid)
        changed["report"]["model"]["model_size_bytes"] = True
        mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(author.AuthoringError, "report_invalid"):
                    author._bind_report(changed, self.packet, MODEL, DIGEST, (TRAIN,))

    def test_excessively_nested_json_has_only_a_fixed_safe_error(self):
        nested = '{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}'
        self.packet_path.write_text(nested)
        with self.assertRaisesRegex(author.AuthoringError, "^dataset_invalid$"):
            author._load_packet(self.packet_path)
        with mock.patch("afk_grinder.local_model_transport.generate_local",
                        return_value=(nested, receipt())):
            with self.assertRaisesRegex(author.AuthoringError, "^proposal_invalid$"):
                author.author_examples(self.packet, self.root, MODEL, DIGEST, (TRAIN,), consent=True)

    def test_new_output_is_exclusive_and_no_raw_errors_are_persisted(self):
        path = self.root / "result.json"
        author.write_output(path, {"ok": False, "error": "model_unavailable"})
        original = path.read_bytes()
        with self.assertRaisesRegex(author.AuthoringError, "output_invalid"):
            author.write_output(path, {"ok": True})
        self.assertEqual(path.read_bytes(), original)
        if __import__("os").name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(author.AuthoringError, "dataset_invalid"):
            author._load_packet(self.root / "missing.json")

    def test_parent_uses_private_metadata_snapshot_and_enforces_process_timeout(self):
        report, _ = self.invoke()
        def child(command, **kwargs):
            snapshot = Path(command[command.index("--author-worker") + 1])
            target = Path(command[command.index("--author-output") + 1])
            self.assertNotEqual(snapshot, self.packet_path)
            self.assertEqual(parse_training_packet(snapshot.read_text()), self.packet)
            self.assertEqual(kwargs["timeout"], 60.0)
            self.assertEqual(command[command.index("--author-example") + 1], TRAIN)
            author.write_output(target, {"ok": True, "report": report})
            return SimpleNamespace(returncode=0)
        with mock.patch.object(author.subprocess, "run", side_effect=child):
            returned = author.run_authoring(self.packet_path, self.root, MODEL, DIGEST, (TRAIN,), consent=True)
        self.assertEqual(returned, report)
        with mock.patch.object(author.subprocess, "run", side_effect=subprocess.TimeoutExpired("redacted", 60)):
            with self.assertRaisesRegex(author.AuthoringError, "^timeout$"):
                author.run_authoring(self.packet_path, self.root, MODEL, DIGEST, (TRAIN,), consent=True)

    def start_server(self, *, cloud_disabled=True):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, value):
                encoded = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                owner.calls.append((self.command, self.path, None))
                if self.path == "/api/status":
                    self.reply({"cloud": {"disabled": cloud_disabled, "source": "env"}})
                elif self.path == "/api/version":
                    self.reply({"version": "0.40.6"})
                elif self.path == "/api/tags":
                    self.reply({"models": [{"name": MODEL, "model": MODEL, "digest": DIGEST,
                                             "size": 1024, "details": {"format": "gguf"}}]})
                else:
                    self.send_error(404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.calls.append((self.command, self.path, body))
                if self.path == "/api/show":
                    self.reply({"capabilities": ["completion", "vision"],
                                "details": {"format": "gguf"},
                                "model_info": {"general.architecture": "synthetic"}})
                elif self.path == "/api/generate":
                    self.reply({"model": MODEL, "done": True, "done_reason": "stop",
                                "response": json.dumps(proposal())})
                else:
                    self.send_error(404)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.addCleanup(close)
        return server.server_address[1]

    def protocol_client(self, port):
        executable = os.environ.get("AFK_GRINDER_TEST_AUTHOR_EXECUTABLE")
        if executable is None:
            return author.run_authoring(self.packet_path, self.root, MODEL, DIGEST,
                                        (TRAIN,), consent=True, port=port)
        executable = str(Path(executable).resolve(strict=True))
        # CI can exercise the public frozen command and its frozen child using
        # the same original synthetic fixtures and strict parent binding.
        output = self.root / "frozen-authoring.json"
        result = subprocess.run([executable, "--author-local", str(self.packet_path),
                                 "--fixture-directory", str(self.root),
                                 "--author-model", MODEL, "--author-digest", DIGEST,
                                 "--author-example", TRAIN, "--author-output", str(output),
                                 "--author-consent", "--author-port", str(port)],
                                timeout=70, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                check=False)
        body = json.loads(output.read_bytes())
        self.assertEqual(result.returncode, 0 if body.get("ok") is True else 1)
        return author._bind_report(body, self.packet, MODEL, DIGEST, (TRAIN,))

    def test_real_disposable_worker_with_synthetic_loopback_protocol(self):
        port = self.start_server()
        report = self.protocol_client(port)
        self.assertEqual(report["model"], receipt())
        self.assertEqual(report["selected_examples"], [TRAIN])
        generates = [body for method, route, body in self.calls if route == "/api/generate"]
        self.assertEqual(len(generates), 1)
        self.assertEqual(len(generates[0]["images"]), 1)
        self.assertEqual(generates[0]["keep_alive"], 0)
        self.assertIs(generates[0]["stream"], False)
        self.assertEqual(report["packet"]["examples"], json.loads(_canonical_packet_json(self.packet))["examples"])

    def test_real_worker_sends_no_images_when_cloud_status_is_not_disabled(self):
        port = self.start_server(cloud_disabled=False)
        with self.assertRaisesRegex(author.AuthoringError, "cloud_required"):
            self.protocol_client(port)
        self.assertNotIn("/api/generate", [route for _, route, _ in self.calls])


if __name__ == "__main__":
    unittest.main()
