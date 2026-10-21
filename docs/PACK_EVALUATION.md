# Local pack evaluation

The local evaluator checks one already loaded `afk-resource-pack` against one
explicitly selected split from one validated `afk-grinder-training` packet. It
is static classification evidence. It does not capture a window, send input,
approve a pack, establish temporal stability, or prove live readiness.

## Run a selected fixture set

Use the optional pinned SDK from the README's
[recognition development setup](../README.md). The evaluator performs no
dependency or model downloads. Current downloadable prototypes are SDK-free;
they report `recognition_failed` on this demo's supported frames rather than
silently substituting a different matcher. Template evaluation requires no OCR
model files.

Create an original synthetic demo in a new directory:

```text
.venv/bin/python -m tools.make_fixture_demo --destination NEWDIR
```

The command creates `pack/`, `training.json`, and `fixtures/`. Its images are
original synthetic test textures. They contain no game art, screenshots, replay
data, model weights, or private assets. The command never overwrites an
existing destination.

Evaluate the default held-out split:

```text
.venv/bin/python -m afk_grinder \
  --evaluate-pack NEWDIR/pack \
  --training-packet NEWDIR/training.json \
  --fixture-directory NEWDIR/fixtures \
  --fixture-consent \
  --fixture-report NEWFILE
```

`--fixture-consent` is required. It authorizes reading only the fixture files
named by the selected packet split. The evaluator does not search the fixture
directory. Select another packet split only with
`--fixture-split train|validation|held_out`; default is `held_out`. The selected
split must contain 1–64 examples. The report path must name a new file in an
existing parent directory.

Each selected file is read through canonical-path and regular-file checks,
then hash-checked before decoding. Image format and dimensions must match its
metadata before pixels are accepted. Decoded pixels stay in memory. The report carries
labels, scores, boxes, dimensions, latency, variant counts, confusion counts,
and safety counters; it carries no image bytes, fixture paths, or native text. The report
explicitly records `temporal_stability_evaluated: false`, `live_readiness:
false`, `approved: false`, `native_input: false`, `screen_capture: false`,
`persistent_images: false`, and `model_training: false`.

The parent independently loads pack and packet metadata, then binds the report
to their identities and the exact selected example IDs, expected labels,
kinds, dimensions, and pack anchors. It recomputes confusion and safety counts
from validated rows. These checks establish report consistency; recognition
accuracy still requires reviewed fixtures and independent evidence.

Evaluation runs recognition and image decoding in a disposable child process
with a 120-second whole-process deadline and a two-second deadline for each
template-matching batch. Native output is discarded. This child boundary is a lifetime
bound, not an operating-system sandbox. The evaluator has no runtime LLM or
fine-tuning path.

## Compiler limits and meaning

The runtime pack compiler consumes a validated, immutable resource-pack snapshot
and produces engine-owned in-memory matcher templates. It is separate from any
future training-to-pack proposal compiler. A training packet remains draft
metadata and cannot install or generate a runtime pack.

Compiler safeguards include:

- 576 compiled templates maximum and 4,000,000 compiled template pixels;
- 64,000,000 summed variant ROI pixels and 9 scale variants per anchor;
- 16,000,000 physical frame pixels and 4,000,000 decoded source-asset pixels;
- reference-to-content ROI mapping with aspect ratio within 1% and the pack's
  minimum content size;
- uniform scale derived from the smaller viewport/reference axis, with no
  stretching; requested template sizes must remain 8–512 pixels per axis.

Static state classification can return candidate, blocked, or unknown. Recognized
popup, transaction, loading, and disconnected states return blocked. A matching
exclusion blocks all candidates; ambiguous evidence returns unknown. A candidate
result is not a stable state and does not authorize input. The protected-error
counter counts any fixture labeled with a non-gameplay kind that is incorrectly
predicted as a candidate.

## Current evidence boundary

The local synthetic proof evaluated 9 held-out examples: 5 exact label matches,
0 unsafe protected predictions, plus intentional ambiguous, unknown, and
excluded outcomes. This is useful compiler/evaluator evidence only. It is not
an Adopt Me held-out result and does not complete BUILD.md M2.

[CI run 39522539510](https://github.com/hypler-dev/afk-grinder/actions/runs/39522539510)
passed Windows x64, Mac Apple Silicon, and Intel Mac for source
`32b6cfda4b745379bc96324b9d61d2a6ed0d82e4`. Every private frozen SDK build
passes the exact nine expected fixture outcomes; every SDK-free downloadable
build returns the expected `recognition_failed` result for this demo. All six
download records passed separate static artifact review. No downloaded app was
launched or installed, and this does not establish live-game acceptance.

SDK-bearing distribution and installers remain closed. The current app is
unchanged by this evaluator. No screenshots, replay, model weights, game
assets, native input, capture, live approval, or publication occurred.
