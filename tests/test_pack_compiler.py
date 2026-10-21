"""Synthetic in-memory PNG proof for restricted resource-pack compilation."""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import struct
import unittest
from unittest.mock import patch
import zlib

from PIL import Image

from afk_grinder.recognition.observation import Rect
from afk_grinder.recognition.pack_compiler import (
    MAX_COMPILED_TEMPLATE_PIXELS,
    MAX_SUMMED_VARIANT_ROI_PIXELS,
    PackCompileError,
    compile_pack,
)
from afk_grinder.recognition.packs import (
    Anchor, Asset, MAX_ASSET_BYTES, Provenance, ResourcePack, Setup, State,
)


def png_bytes(image: Image.Image, *, metadata: bool = False) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    data = output.getvalue()
    if not metadata:
        return data
    payload = b"note\x00untrusted metadata"
    chunk = b"tEXt"
    encoded = struct.pack(">I", len(payload)) + chunk + payload
    encoded += struct.pack(">I", zlib.crc32(payload, zlib.crc32(chunk)) & 0xFFFFFFFF)
    return data[:33] + encoded + data[33:]


def png_with_chunk(data: bytes, kind: bytes, payload: bytes = b"") -> bytes:
    encoded = struct.pack(">I", len(payload)) + kind + payload
    encoded += struct.pack(">I", zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF)
    return data[:-12] + encoded + data[-12:]


def patterned_image(size: tuple[int, int] = (12, 12), *, alpha: int | None = None) -> Image.Image:
    mode = "RGBA" if alpha is not None else "RGB"
    image = Image.new(mode, size)
    for y in range(size[1]):
        for x in range(size[0]):
            value = ((x * 17) % 256, (y * 31) % 256, ((x + y) * 19) % 256)
            image.putpixel((x, y), (*value, alpha) if alpha is not None else value)
    return image


def pack_for(
    image: Image.Image | None = None,
    *,
    reference_size: tuple[int, int] = (100, 50),
    minimum: tuple[int, int] = (8, 8),
    anchors: tuple[Anchor, ...] | None = None,
    data: bytes | None = None,
) -> ResourcePack:
    data = png_bytes(patterned_image() if image is None else image) if data is None else data
    asset = Asset("hud.icon", "assets/hud.png", sha256(data).hexdigest(), data)
    anchors = anchors or (Anchor("hud.anchor", "hud.icon", (10, 5, 80, 40), 0.8, (1.0, 1.0)),)
    return ResourcePack(
        "adopt-me.test", "0.1.0", "0.1.0",
        Provenance("https://example.test/pack", "a" * 40, "MIT", "Synthetic"),
        reference_size, Setup("en", "Synthetic pack", minimum), (asset,), anchors,
        (State("known", (anchors[0].id,), (), 2),),
    )


class PackCompilerTests(unittest.TestCase):
    def test_compiles_bgr_geometric_scales_and_inward_offset_roi(self):
        anchor = Anchor("hud.anchor", "hud.icon", (10, 5, 20, 30), 0.8, (0.5, 2.0))
        image = patterned_image((10, 10))
        image.putpixel((0, 0), (1, 2, 3))
        pack = pack_for(image, anchors=(anchor,))

        compiled = compile_pack(pack, (300, 150), viewport=Rect(10, 20, 200, 100))

        self.assertEqual(compiled.frame_size, (300, 150))
        self.assertEqual({item.anchor_id for item in compiled.templates}, {"hud.anchor"})
        self.assertEqual(len(compiled.templates), 9)
        self.assertEqual(compiled.templates[0].spec.roi, (30, 30, 40, 60))
        dimensions = {(item.spec.width, item.spec.height) for item in compiled.templates}
        self.assertIn((10, 10), dimensions)
        self.assertIn((20, 20), dimensions)
        self.assertIn((40, 40), dimensions)
        first = next(item.spec for item in compiled.templates if (item.spec.width, item.spec.height) == (10, 10))
        self.assertEqual(first.pixels[:3], bytes((3, 2, 1)))
        self.assertTrue(all(item.spec.template_id.startswith("p00s") for item in compiled.templates))

    def test_inward_rounding_aspect_and_minimum_content_fail_closed(self):
        anchor = Anchor("hud.anchor", "hud.icon", (0, 0, 10, 10), 0.8, (1.0, 1.0))
        pack = pack_for(patterned_image((8, 8)), anchors=(anchor,))
        compiled = compile_pack(pack, (210, 110), viewport=Rect(0.2, 0.1, 200.4, 100.2))
        self.assertEqual(compiled.templates[0].spec.roi, (1, 1, 19, 19))
        with self.assertRaises(PackCompileError):
            compile_pack(pack, (210, 110), viewport=Rect(0, 0, 200, 98))
        with self.assertRaises(PackCompileError):
            compile_pack(replace(pack, setup=replace(pack.setup, min_content_size=(201, 101))), (200, 100))

    def test_all_sixty_four_anchors_compile_with_tight_search_regions(self):
        anchors = tuple(
            Anchor(f"a{index}", "hud.icon", ((index % 8) * 8, (index // 8) * 8, 8, 8), 0.7, (1.0, 1.0))
            for index in range(64)
        )
        pack = pack_for(patterned_image((8, 8)), reference_size=(64, 64), anchors=anchors)

        compiled = compile_pack(pack, (64, 64))

        self.assertEqual(len(compiled.templates), 64)
        self.assertEqual(len({item.spec.template_id for item in compiled.templates}), 64)
        self.assertEqual({item.anchor_id for item in compiled.templates}, {anchor.id for anchor in anchors})

    def test_sixty_four_anchors_by_nine_scales_reaches_compiler_limit(self):
        anchors = tuple(
            Anchor(f"a{index}", "hud.icon", (0, 0, 64, 64), 0.7, (0.5, 2.0))
            for index in range(64)
        )
        pack = pack_for(patterned_image((16, 16)), reference_size=(64, 64), anchors=anchors)

        compiled = compile_pack(pack, (64, 64))

        self.assertEqual(len(compiled.templates), 576)
        self.assertEqual(len({item.spec.template_id for item in compiled.templates}), 576)
        self.assertEqual({item.anchor_id for item in compiled.templates}, {anchor.id for anchor in anchors})
        self.assertTrue(all(item.spec.template_id.startswith("p") for item in compiled.templates))

    def test_geometry_and_workload_limits_fail_without_silently_dropping_variants(self):
        small_roi = pack_for(patterned_image((8, 8)), anchors=(
            Anchor("hud.anchor", "hud.icon", (0, 0, 4, 4), 0.8, (1.0, 1.0)),
        ))
        with self.assertRaisesRegex(PackCompileError, "ROI"):
            compile_pack(small_roi, (100, 50))

        oversized = pack_for(patterned_image((512, 512)), anchors=(
            Anchor("hud.anchor", "hud.icon", (0, 0, 100, 50), 0.8, (2.0, 2.0)),
        ))
        with self.assertRaisesRegex(PackCompileError, "dimensions"):
            compile_pack(oversized, (100, 50))

        many = tuple(Anchor(f"a{index}", "hud.icon", (0, 0, 256, 256), 0.8, (1.0, 1.0)) for index in range(64))
        pixel_limited = pack_for(patterned_image((256, 256)), reference_size=(256, 256), anchors=many)
        self.assertGreater(64 * 256 * 256, MAX_COMPILED_TEMPLATE_PIXELS)
        with self.assertRaisesRegex(PackCompileError, "pixels"):
            compile_pack(pixel_limited, (256, 256))

        roi_limited = pack_for(patterned_image((16, 16)), reference_size=(4000, 4000), anchors=(
            Anchor("hud.anchor", "hud.icon", (0, 0, 4000, 4000), 0.8, (0.5, 2.0)),
        ))
        self.assertGreater(5 * 4000 * 4000, MAX_SUMMED_VARIANT_ROI_PIXELS)
        with self.assertRaisesRegex(PackCompileError, "search work"):
            compile_pack(roi_limited, (4000, 4000))

    def test_corrupt_hash_snapshot_apng_and_unknown_critical_fail_before_decoder(self):
        pack = pack_for(patterned_image((8, 8)))
        bad_hash = replace(pack, assets=(replace(pack.assets[0], sha256="0" * 64),))
        bad_snapshot = replace(pack, anchors=(replace(pack.anchors[0], threshold=True),))
        apng = replace(pack, assets=(replace(pack.assets[0], data=png_with_chunk(pack.assets[0].data, b"acTL", b"\0" * 8)),))
        apng = replace(apng, assets=(replace(apng.assets[0], sha256=sha256(apng.assets[0].data).hexdigest()),))
        critical = replace(pack, assets=(replace(pack.assets[0], data=png_with_chunk(pack.assets[0].data, b"ABCD")),))
        critical = replace(critical, assets=(replace(critical.assets[0], sha256=sha256(critical.assets[0].data).hexdigest()),))
        too_large_data = b"x" * (MAX_ASSET_BYTES + 1)
        too_large = replace(pack, assets=(replace(pack.assets[0], data=too_large_data,
                                                 sha256=sha256(too_large_data).hexdigest()),))

        with patch("afk_grinder.recognition.pack_compiler.Image.open") as decode:
            for candidate in (bad_hash, bad_snapshot, apng, critical, too_large):
                with self.subTest(candidate=candidate), self.assertRaises((PackCompileError, TypeError)):
                    compile_pack(candidate, (100, 50))
            decode.assert_not_called()

    def test_ancillary_metadata_is_stripped_before_decoder(self):
        data = png_bytes(patterned_image((8, 8)), metadata=True)
        pack = pack_for(patterned_image((8, 8)), data=data)
        real_open = Image.open

        def decoder(stream):
            self.assertNotIn(b"untrusted metadata", stream.getvalue())
            return real_open(stream)

        with patch("afk_grinder.recognition.pack_compiler.Image.open", side_effect=decoder):
            compiled = compile_pack(pack, (100, 50))
        self.assertEqual(len(compiled.templates), 1)

    def test_transparent_and_flat_templates_reject_without_native_matcher(self):
        transparent = pack_for(patterned_image((8, 8), alpha=127))
        flat = pack_for(Image.new("RGB", (8, 8), (5, 10, 20)))
        with self.assertRaisesRegex(PackCompileError, "transparent"):
            compile_pack(transparent, (100, 50))
        with self.assertRaisesRegex(PackCompileError, "flat"):
            compile_pack(flat, (100, 50))


if __name__ == "__main__":
    unittest.main()
