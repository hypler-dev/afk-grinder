"""Matcher tests use synthetic BGR buffers only; no desktop capture or input."""

import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from afk_grinder.recognition import matcher


TEMPLATE_BYTES = bytes(range(8 * 8 * 3))


class FakeArray:
    def reshape(self, shape):
        return self


class FakeNumpy:
    uint8 = "uint8"

    @staticmethod
    def frombuffer(*args, **kwargs):
        return FakeArray()

    @staticmethod
    def zeros(*args, **kwargs):
        return FakeArray()


def spec(template_id="template", *, roi=(0, 0, 16, 16), threshold=0.95):
    return matcher.TemplateSpec(template_id, 8, 8, TEMPLATE_BYTES, roi, threshold)


class MatcherValidationTests(unittest.TestCase):
    def test_template_spec_rejects_invalid_metadata_before_sdk_use(self):
        cases = (
            {"width": True}, {"height": 7}, {"pixels": b"x"}, {"roi": [0, 0, 16, 16]},
            {"roi": (0, 0, 0, 16)}, {"threshold": True}, {"threshold": float("nan")},
            {"threshold": 1.01}, {"template_id": ""},
        )
        for changes in cases:
            values = {"template_id": "template", "width": 8, "height": 8,
                      "pixels": TEMPLATE_BYTES,
                      "roi": (0, 0, 16, 16), "threshold": 0.95}
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                matcher.TemplateSpec(**values)

    def test_match_rejects_invalid_frame_and_roi_before_sdk_initialization(self):
        instance = matcher.TemplateMatcher([spec(roi=(1, 1, 16, 16))])
        with patch.object(instance, "_ensure_initialized") as initialize:
            for width, height, pixels in ((True, 16, b""), (16, 16, b"x"), (16, 16, bytes(16 * 16 * 3))):
                with self.subTest(width=width, height=height, size=len(pixels)), self.assertRaises(ValueError):
                    instance.match(width, height, pixels)
            initialize.assert_not_called()

    def test_template_and_frame_caps_are_enforced(self):
        base = spec()
        with self.assertRaises(ValueError):
            matcher.TemplateMatcher([base] * 17)
        large = matcher.TemplateSpec("large", 512, 512, bytes(512 * 512 * 3), (0, 0, 512, 512), 0.9)
        large_two = matcher.TemplateSpec("large_two", 512, 512, bytes(512 * 512 * 3), (0, 0, 512, 512), 0.9)
        self.assertEqual(len(matcher.TemplateMatcher([large, large_two])._specs), 2)
        with self.assertRaises(ValueError):
            matcher.TemplateMatcher([large, large_two, matcher.TemplateSpec(
                "large_three", 512, 512, bytes(512 * 512 * 3), (0, 0, 512, 512), 0.9
            ), matcher.TemplateSpec(
                "large_four", 512, 512, bytes(512 * 512 * 3), (0, 0, 512, 512), 0.9
            )])
        instance = matcher.TemplateMatcher([base])
        with patch.object(instance, "_ensure_initialized") as initialize, self.assertRaises(ValueError):
            instance.match(4001, 4000, b"")
        initialize.assert_not_called()


class MatcherSdkBoundaryTests(unittest.TestCase):
    def fake_modules(self):
        completed = SimpleNamespace(done=True, succeeded=True)
        tasker = Mock()
        tasker.bind.return_value = True
        tasker.post_stop.return_value = completed
        tasker_type = Mock(return_value=tasker)
        for name in ("set_log_dir", "set_save_draw", "set_save_on_error", "set_debug_mode",
                     "set_stdout_level", "set_reco_image_cache_limit"):
            getattr(tasker_type, name).return_value = True
        resource = Mock()
        resource.set_cpu.return_value = True

        class ControllerBase:
            def __init__(self):
                pass

            def post_connection(self):
                return completed

        modules = {
            "maa.library": SimpleNamespace(Library=SimpleNamespace(version=lambda: "v5.14.3")),
            "maa.tasker": SimpleNamespace(Tasker=tasker_type),
            "maa.resource": SimpleNamespace(Resource=lambda: resource),
            "maa.controller": SimpleNamespace(CustomController=ControllerBase),
            "maa.define": SimpleNamespace(LoggingLevelEnum=SimpleNamespace(Off=0)),
            "maa.pipeline": SimpleNamespace(),
            "numpy": FakeNumpy,
        }
        return modules, tasker_type, tasker, resource

    def test_initialization_requires_safety_options_cpu_templates_and_read_only_controller(self):
        modules, tasker_type, tasker, resource = self.fake_modules()
        instance = matcher.TemplateMatcher([spec()])
        with patch.dict(matcher.os.environ, {}, clear=True), \
             patch.object(matcher.importlib.metadata, "version", return_value="5.14.3"), \
             patch.object(matcher.importlib.util, "find_spec", return_value=object()), \
             patch.object(matcher.importlib, "import_module", side_effect=modules.__getitem__):
            instance._ensure_initialized()

        tasker_type.set_log_dir.assert_called_once_with("")
        tasker_type.set_save_draw.assert_called_once_with(False)
        tasker_type.set_save_on_error.assert_called_once_with(False)
        tasker_type.set_debug_mode.assert_called_once_with(False)
        tasker_type.set_reco_image_cache_limit.assert_called_once_with(2)
        resource.set_cpu.assert_called_once_with()
        resource.override_image.assert_called_once()
        controller = tasker.bind.call_args.args[1]
        self.assertFalse(controller.click(1, 2))
        self.assertFalse(controller.key_down(1))
        self.assertFalse(controller.start_app("ignored"))
        self.assertEqual(controller.get_features(), 0)
        instance.close()
        tasker.post_stop.assert_called_once_with()

    def test_override_or_unpinned_distribution_fails_before_native_import(self):
        instance = matcher.TemplateMatcher([spec()])
        with patch.dict(matcher.os.environ, {"MAAFW_BINARY_PATH": "/untrusted"}), \
             patch.object(matcher.importlib, "import_module") as imports, \
             self.assertRaises(matcher.SDKError):
            instance._ensure_initialized()
        imports.assert_not_called()
        instance = matcher.TemplateMatcher([spec()])
        with patch.dict(matcher.os.environ, {}, clear=True), \
             patch.object(matcher.importlib.metadata, "version", return_value="5.14.2"), \
             patch.object(matcher.importlib, "import_module") as imports, \
             self.assertRaises(matcher.SDKError):
            instance._ensure_initialized()
        imports.assert_not_called()

    def test_native_exception_is_sanitized_and_never_returns_pixels(self):
        instance = matcher.TemplateMatcher([spec()])
        tasker = Mock()
        tasker.post_recognition.side_effect = RuntimeError("SENSITIVE_MATCHER_MARKER /private/frame")
        instance._tasker = tasker
        with self.assertRaises(matcher.SDKError) as raised:
            instance.match(16, 16, bytes(16 * 16 * 3))
        self.assertEqual(str(raised.exception), "Recognition match failed.")
        self.assertNotIn("SENSITIVE_", str(raised.exception))
        self.assertNotIn("/private/", str(raised.exception))

    def test_template_threshold_is_applied_after_floor_recognition(self):
        result = SimpleNamespace(score=0.5, box=(2, 3, 8, 8))
        recognition = SimpleNamespace(hit=True, best_result=result)
        detail = SimpleNamespace(nodes=[SimpleNamespace(recognition=recognition)])
        job = SimpleNamespace(done=True, succeeded=True, get=lambda: detail)
        tasker = Mock()
        tasker.post_recognition.return_value = job
        instance = matcher.TemplateMatcher([spec(roi=(0, 0, 16, 16), threshold=0.95)])
        instance._tasker = tasker
        pipeline = SimpleNamespace(
            JRecognitionType=SimpleNamespace(TemplateMatch="TemplateMatch"),
            JTemplateMatch=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        with patch.object(matcher.importlib, "import_module", side_effect={
            "numpy": FakeNumpy, "maa.pipeline": pipeline,
        }.__getitem__):
            hit = instance.match(16, 16, bytes(16 * 16 * 3))[0]

        parameter = tasker.post_recognition.call_args.args[1]
        self.assertEqual(parameter.threshold, [0.0])
        self.assertEqual(hit, matcher.TemplateHit("template", 0.5, None))

    def test_template_rejects_string_score_and_out_of_roi_box(self):
        for result in (
            SimpleNamespace(score="0.9", box=(2, 3, 8, 8)),
            SimpleNamespace(score=0.9, box=(10, 10, 8, 8)),
        ):
            with self.subTest(result=result):
                recognition = SimpleNamespace(hit=True, best_result=result)
                detail = SimpleNamespace(nodes=[SimpleNamespace(recognition=recognition)])
                job = SimpleNamespace(done=True, succeeded=True, get=lambda: detail)
                tasker = Mock()
                tasker.post_recognition.return_value = job
                instance = matcher.TemplateMatcher([spec(roi=(0, 0, 16, 16))])
                instance._tasker = tasker
                pipeline = SimpleNamespace(
                    JRecognitionType=SimpleNamespace(TemplateMatch="TemplateMatch"),
                    JTemplateMatch=lambda **kwargs: SimpleNamespace(**kwargs),
                )
                with patch.object(matcher.importlib, "import_module", side_effect={
                    "numpy": FakeNumpy, "maa.pipeline": pipeline,
                }.__getitem__), self.assertRaises(matcher.SDKError):
                    instance.match(16, 16, bytes(16 * 16 * 3))


class LabelMatcherTests(unittest.TestCase):
    def test_closed_label_matcher_cannot_warm_native_resources(self):
        instance = matcher.LabelMatcher(Path.cwd(), {"bank": "bank"})
        instance.close()
        with patch.object(instance, "_ensure_initialized") as initialize:
            with self.assertRaises(matcher.SDKError):
                instance.warmup()
        initialize.assert_not_called()

    def test_label_configuration_and_metadata_are_bounded(self):
        with self.assertRaises(ValueError):
            matcher.LabelMatcher(Path.cwd(), {"not valid": "trade"})
        with self.assertRaises(ValueError):
            matcher.LabelMatcher(Path.cwd(), {"trade": "x" * 129})
        instance = matcher.LabelMatcher(Path.cwd(), {"trade": r"trade", "purchase": r"buy"})
        results = [
            SimpleNamespace(text="TRADE", score=0.9, box=(1, 2, 3, 4)),
            SimpleNamespace(text="account-551", score=0.8, box=(5, 6, 3, 4)),
        ]
        detail = SimpleNamespace(nodes=[SimpleNamespace(recognition=SimpleNamespace(hit=True, all_results=results))])

        hits = instance._label_hits(detail, 16, 16)

        self.assertEqual(hits, (matcher.LabelHit("trade", 0.9, (1, 2, 3, 4)),))
        self.assertNotIn("account", repr(hits))

    def test_label_result_cap_and_invalid_raw_text_fail_closed(self):
        instance = matcher.LabelMatcher(Path.cwd(), {"trade": r"trade"})
        capped = SimpleNamespace(nodes=[SimpleNamespace(recognition=SimpleNamespace(
            hit=True, all_results=[object()] * 513
        ))])
        with self.assertRaises(matcher.SDKError) as raised:
            instance._label_hits(capped, 16, 16)
        self.assertEqual(str(raised.exception), "Recognition returned invalid metadata.")
        invalid = SimpleNamespace(nodes=[SimpleNamespace(recognition=SimpleNamespace(
            hit=True, all_results=[SimpleNamespace(
                text="SENSITIVE_ACCOUNT_551", score="0.9", box=(1, 2, 3, 4)
            )]
        ))])
        with self.assertRaises(matcher.SDKError) as raised:
            instance._label_hits(invalid, 16, 16)
        self.assertEqual(str(raised.exception), "Recognition returned invalid metadata.")
        self.assertNotIn("SENSITIVE_", str(raised.exception))

    def test_label_matcher_initializes_pinned_cpu_read_only_ocr_model(self):
        modules, tasker_type, tasker, resource = MatcherSdkBoundaryTests().fake_modules()
        completed = SimpleNamespace(done=True, succeeded=True)
        resource.post_ocr_model.return_value = completed
        instance = matcher.LabelMatcher(Path.cwd(), {"trade": r"trade"})
        with patch.dict(matcher.os.environ, {}, clear=True), \
             patch.object(matcher.importlib.metadata, "version", return_value="5.14.3"), \
             patch.object(matcher.importlib.util, "find_spec", return_value=object()), \
             patch.object(matcher.importlib, "import_module", side_effect=modules.__getitem__):
            instance.warmup()
            instance.warmup()

        resource.post_ocr_model.assert_called_once_with(Path.cwd())
        tasker_type.set_save_draw.assert_called_once_with(False)
        tasker_type.set_save_on_error.assert_called_once_with(False)
        controller = tasker.bind.call_args.args[1]
        self.assertFalse(controller.click(1, 2))
        self.assertFalse(controller.input_text("ignored"))


class LabelMatcherNativeModelTests(unittest.TestCase):
    def test_pinned_model_filters_synthetic_ocr_text_to_known_labels(self):
        model_path = os.environ.get("AFK_GRINDER_TEST_OCR_MODEL_DIR")
        if not model_path:
            self.skipTest("Set AFK_GRINDER_TEST_OCR_MODEL_DIR to run the pinned OCR model proof.")
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (800, 400), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=64)
        draw.text((60, 70), "BANK", fill="black", font=font)
        draw.text((60, 190), "RECONNECT", fill="black", font=font)
        instance = matcher.LabelMatcher(Path(model_path), {"bank": r"bank", "reconnect": r"reconnect"})
        try:
            hits = instance.match_labels(800, 400, image.tobytes("raw", "BGR"))
        finally:
            instance.close()

        self.assertEqual(tuple(hit.label_id for hit in hits), ("bank", "reconnect"))
        self.assertTrue(all(0 <= hit.score <= 1 and len(hit.box) == 4 for hit in hits))


class MatcherNativeSubprocessTests(unittest.TestCase):
    def test_pinned_sdk_matches_synthetic_exact_and_rejects_near_and_missing(self):
        try:
            importlib.metadata.version("MaaFw")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest(matcher.OPTIONAL_SDK_MESSAGE)
        source_root = Path(__file__).resolve().parents[1] / "src"
        script = """
import numpy
from afk_grinder.recognition.matcher import TemplateMatcher, TemplateSpec

template = numpy.arange(8 * 8 * 3, dtype=numpy.uint8).reshape(8, 8, 3)
spec = TemplateSpec('synthetic', 8, 8, template.tobytes(), (0, 0, 24, 24), 1.0)
matcher = TemplateMatcher([spec])
try:
    exact = numpy.full((24, 24, 3), 200, dtype=numpy.uint8)
    exact[7:15, 9:17] = template
    hit = matcher.match(24, 24, exact.tobytes())[0]
    assert hit.box == (9, 7, 8, 8) and hit.score == 1.0
    near = exact.copy()
    near[7, 9, 0] ^= 255
    near_hit = matcher.match(24, 24, near.tobytes())[0]
    assert near_hit.box is None
    missing = numpy.zeros((24, 24, 3), dtype=numpy.uint8)
    miss = matcher.match(24, 24, missing.tobytes())[0]
    assert miss.box is None
finally:
    matcher.close()
"""
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(source_root)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                timeout=15, check=False, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
