"""Synthetic loopback protocol tests for the local model transport."""

from __future__ import annotations

import base64
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from afk_grinder.local_model_transport import LocalModelError, ModelProfile, generate_local


PROFILE = ModelProfile("afk/qwen3.5:vision", "a" * 64)
JPEG = base64.b64encode(b"\xff\xd8fake\xff\xd9").decode("ascii")


class FakeServer:
    def __init__(self, responses: list[tuple[int, object, dict[str, str] | None]]) -> None:
        self.responses = iter(responses)
        self.requests: list[tuple[str, str, object | None]] = []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        self.port = self.socket.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.socket.close()
        self.thread.join(timeout=1)

    def _run(self) -> None:
        try:
            while True:
                connection, _ = self.socket.accept()
                with connection:
                    data = b""
                    while b"\r\n\r\n" not in data:
                        chunk = connection.recv(4096)
                        if not chunk:
                            return
                        data += chunk
                    headers, body = data.split(b"\r\n\r\n", 1)
                    lines = headers.decode("ascii").split("\r\n")
                    method, path, _ = lines[0].split(" ", 2)
                    size = next((int(line.split(":", 1)[1].strip()) for line in lines[1:] if line.lower().startswith("content-length:")), 0)
                    while len(body) < size:
                        body += connection.recv(4096)
                    self.requests.append((method, path, json.loads(body) if body else None))
                    status, payload, extra_headers = next(self.responses)
                    raw = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
                    response_headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
                    if extra_headers:
                        response_headers.update(extra_headers)
                    response = f"HTTP/1.1 {status} ok\r\n".encode() + b"".join(
                        f"{key}: {value}\r\n".encode() for key, value in response_headers.items()
                    ) + b"\r\n" + raw
                    connection.sendall(response)
        except (OSError, StopIteration):
            return


def status(disabled: bool = True):
    return {"cloud": {"disabled": disabled}}


def tags(digest: str = PROFILE.digest, **extra):
    return {"models": [{"name": PROFILE.name, "model": PROFILE.name, "digest": digest, "size": 1, "details": {"format": "gguf"}, **extra}]}


def show(**extra):
    return {"details": {"format": "gguf"}, "model_info": {"general.architecture": "llama"}, "capabilities": ["completion", "vision"], **extra}


def success_responses():
    return [(200, status(), None), (200, tags(), None), (200, show(), None), (200, {"version": "0.40.6"}, None), (200, {"model": PROFILE.name, "response": "draft", "done": True, "done_reason": "stop"}, None), (200, status(), None), (200, tags(), None)]


class LocalModelTransportTests(unittest.TestCase):
    def call(self, server: FakeServer, **kwargs):
        return generate_local(PROFILE, "write labels", (JPEG,), {"type": "object"}, port=server.port, deadline=1.0, **kwargs)

    def test_valid_request_order_fixed_body_and_bounded_receipt(self):
        with FakeServer(success_responses()) as server:
            text, receipt = self.call(server)
        self.assertEqual(text, "draft")
        self.assertEqual(receipt, {
            "name": PROFILE.name, "digest": PROFILE.digest, "runtime_version": "0.40.6", "model_size_bytes": 1,
            "cloud_disabled": True, "vision": True, "digest_checked_before_after": True,
        })
        self.assertEqual([(method, path) for method, path, _ in server.requests], [
            ("GET", "/api/status"), ("GET", "/api/tags"), ("POST", "/api/show"), ("GET", "/api/version"),
            ("POST", "/api/generate"), ("GET", "/api/status"), ("GET", "/api/tags"),
        ])
        self.assertEqual(server.requests[2][2], {"model": PROFILE.name})
        self.assertEqual(server.requests[4][2], {
            "model": PROFILE.name, "prompt": "write labels", "images": [JPEG], "format": {"type": "object"},
            "stream": False, "keep_alive": 0,
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 1024, "num_thread": 2},
        })

    def test_prerequisite_rejections_never_send_image(self):
        cases = [
            ([(200, status(False), None)], "cloud_required"),
            ([(200, {}, None)], "cloud_required"),
            ([(200, status(), None), (200, tags(remote_model="elsewhere"), None)], "model_invalid"),
            ([(200, status(), None), (200, tags(), None), (200, show(remote_host="https://x"), None)], "model_invalid"),
        ]
        for responses, code in cases:
            with self.subTest(code=code), FakeServer(responses) as server, self.assertRaisesRegex(LocalModelError, f"^{code}$"):
                self.call(server)
            self.assertNotIn(("POST", "/api/generate"), [(method, path) for method, path, _ in server.requests])

    def test_retag_or_remote_generate_discards_output(self):
        responses = success_responses()
        responses[-1] = (200, tags("b" * 64), None)
        with FakeServer(responses) as server, self.assertRaisesRegex(LocalModelError, "^model_changed$"):
            self.call(server)
        responses = success_responses()
        responses[4] = (200, {"model": PROFILE.name, "response": "draft", "done": True, "remote_host": "https://x"}, None)
        with FakeServer(responses) as server, self.assertRaisesRegex(LocalModelError, "^response_invalid$"):
            self.call(server)

    def test_invalid_json_oversize_redirect_timeout_and_truncation_fail_closed(self):
        invalid = [(200, status(), None), (200, b'{"models":[]}', None)]
        with FakeServer(invalid) as server, self.assertRaisesRegex(LocalModelError, "^model_unavailable$"):
            self.call(server)
        large = [(200, b"x" * (2 * 1024 * 1024 + 1), None)]
        with FakeServer(large) as server, self.assertRaisesRegex(LocalModelError, "^response_invalid$"):
            self.call(server)
        redirect = [(302, {}, None)]
        with FakeServer(redirect) as server, self.assertRaisesRegex(LocalModelError, "^response_invalid$"):
            self.call(server)
        with patch("afk_grinder.local_model_transport.http.client.HTTPConnection") as connection:
            connection.side_effect = socket.timeout()
            with self.assertRaisesRegex(LocalModelError, "^timeout$"):
                generate_local(PROFILE, "x", (), {"type": "object"}, port=11434, deadline=1.0)
        truncated = [(200, b'{"cloud":', None)]
        with FakeServer(truncated) as server, self.assertRaisesRegex(LocalModelError, "^response_invalid$"):
            self.call(server)

    def test_invalid_profiles_ports_deadlines_and_images_do_not_connect(self):
        self.assertEqual(ModelProfile("fakefixture-vlm:synthetic-v1", "b" * 64).name, "fakefixture-vlm:synthetic-v1")
        for name, digest in (("afk/qwen3.5:latest", "a" * 64), ("afk/qwen3.5:vision", "A" * 64)):
            with self.subTest(name=name), self.assertRaisesRegex(LocalModelError, "^model_invalid$"):
                ModelProfile(name, digest)
        cases = [
            (PROFILE, True, 1.0, (JPEG,)),
            (PROFILE, 11434, float("nan"), (JPEG,)),
            (PROFILE, 11434, 1.0, ("not-base64",)),
        ]
        for profile, port, deadline, images in cases:
            with self.subTest(port=repr(port), deadline=repr(deadline)), patch("afk_grinder.local_model_transport.http.client.HTTPConnection") as connection:
                with self.assertRaises(LocalModelError):
                    generate_local(profile, "x", images, {"type": "object"}, port=port, deadline=deadline)
                connection.assert_not_called()

    def test_malformed_capability_member_is_sanitized(self):
        responses = [(200, status(), None), (200, tags(), None), (200, show(capabilities=["completion", {"vision": True}]), None)]
        with FakeServer(responses) as server, self.assertRaisesRegex(LocalModelError, "^model_invalid$"):
            self.call(server)

    def test_duplicate_nonfinite_and_deep_json_are_rejected(self):
        malformed = [
            b'{"cloud":{"disabled":true},"cloud":{"disabled":true}}',
            b'{"cloud":{"disabled":NaN}}',
            ("[" * 34 + "0" + "]" * 34).encode(),
        ]
        for payload in malformed:
            with self.subTest(payload=payload[:20]), FakeServer([(200, payload, None)]) as server, self.assertRaisesRegex(LocalModelError, "^response_invalid$"):
                self.call(server)


if __name__ == "__main__":
    unittest.main()
