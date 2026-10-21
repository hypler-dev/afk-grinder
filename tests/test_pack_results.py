"""Pure result-contract checks; no native SDK or capture is used."""

from dataclasses import replace
import unittest

from afk_grinder.recognition.matcher import TemplateHit
from afk_grinder.recognition.observation import Rect
from afk_grinder.recognition.pack_compiler import compile_pack
from afk_grinder.recognition.pack_results import AnchorHit, PackResultError, aggregate_hits, validate_anchor_hits
from tests.test_pack_compiler import pack_for


class PackResultTests(unittest.TestCase):
    def setUp(self):
        self.pack = pack_for()
        self.compiled = compile_pack(self.pack, (100, 50))
        spec = self.compiled.templates[0].spec
        self.hit = TemplateHit(spec.template_id, .95, (10, 5, spec.width, spec.height))

    def test_complete_native_results_aggregate_and_validate(self):
        hits = aggregate_hits(self.pack, self.compiled, (self.hit,))
        self.assertEqual(hits, (AnchorHit("hud.anchor", .95, (10, 5, 12, 12)),))
        self.assertIs(validate_anchor_hits(self.pack, (100, 50), hits), hits)

    def test_missing_duplicate_foreign_and_invalid_variant_results_rejected(self):
        for hits in ((), (self.hit, self.hit), (replace(self.hit, template_id="foreign"),),
                     (replace(self.hit, score=float("nan")),), (replace(self.hit, score=True),),
                     (replace(self.hit, box=(9, 5, 12, 12)),),
                     (replace(self.hit, box=(10, 5, 13, 12)),),
                     (replace(self.hit, score=.2),)):
            with self.subTest(hits=hits), self.assertRaises(PackResultError):
                aggregate_hits(self.pack, self.compiled, hits)

    def test_zero_threshold_miss_remains_missing_evidence(self):
        pack = replace(self.pack, anchors=(replace(self.pack.anchors[0], threshold=0),))
        compiled = compile_pack(pack, (100, 50))
        hit = TemplateHit(compiled.templates[0].spec.template_id, 0, None)
        self.assertEqual(aggregate_hits(pack, compiled, (hit,)), (AnchorHit("hud.anchor", None, None),))

    def test_offset_compiled_viewport_uses_compiled_roi(self):
        compiled = compile_pack(self.pack, (150, 90), viewport=Rect(30, 20, 100, 50))
        spec = compiled.templates[0].spec
        hit = TemplateHit(spec.template_id, .95, (40, 25, spec.width, spec.height))
        self.assertEqual(aggregate_hits(self.pack, compiled, (hit,))[0].box, (40, 25, 12, 12))

    def test_parent_rejects_wrong_identity_layout_score_and_box(self):
        valid = AnchorHit("hud.anchor", .95, (10, 5, 12, 12))
        for hit in (replace(valid, id="foreign"), replace(valid, score=float("inf")),
                    replace(valid, score=True), replace(valid, score=.2), replace(valid, box=None),
                    replace(valid, box=(9, 5, 12, 12)), replace(valid, box=(10, 5, 7, 12))):
            with self.subTest(hit=hit), self.assertRaises(PackResultError):
                validate_anchor_hits(self.pack, (100, 50), (hit,))
        for size in ((100, 49), (4, 2), (True, 50), (100_000, 50_000)):
            with self.subTest(size=size), self.assertRaises(PackResultError):
                validate_anchor_hits(self.pack, size, (valid,))
        with self.assertRaises(PackResultError):
            validate_anchor_hits(self.pack, (100, 50), ())


if __name__ == "__main__":
    unittest.main()
