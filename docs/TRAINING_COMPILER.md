# Training draft to recognition candidate

Authority: [intent.md](../intent.md), BUILD.md sections 6–7 and milestone 2. This offline conversion uses a separately reviewed crop recipe and explicitly selected train images. It produces a local, unapproved recognition candidate, never an executable routine or an approved game pack.

The CLI and strict builder are implemented; exact validation and build evidence is in [plan.md](../plan.md). Native calibration, actual Adopt Me fixtures, held-out accuracy and care-task acceptance remain separate gates.

## Recipe contract

The recipe is a separate strict JSON object with exactly `format`, `schema_version`, `pack_id`, `pack_version`, `provenance`, `setup`, `anchors` and `states`. Its format is `afk-training-pack-recipe`, schema version is integer `1`, and its pack identity and provenance obey the existing resource-pack contract. Provenance has `source`, `revision`, `license` and `attribution`; these remain human-supplied claims, not permission or legal approval.

`setup` has exactly `instructions` and `min_content_size`. Language and reference size come from the original training packet. Every training state must appear exactly once in the recipe's `states`, with `id`, `positive`, `exclude` and `stable_frames`. The state kind always comes from the original packet; recipes cannot supply or change it. Positive anchors for a state must come from train examples with that same label. Exclusions may refer to other selected anchors. All existing pack constraints remain in force; unsupported IDs, more than 32 states or insufficient train evidence fail rather than dropping states.

Each anchor has exactly `id`, `example_id`, `crop`, `roi`, `threshold` and `scale_range`. `crop` is `[x, y, width, height]` in the selected source image's pixels; `roi` uses the training packet's reference pixels. Every value in either rectangle is a strict integer, with nonnegative origins and positive sizes. The source image must have the same aspect ratio as the reference. Crops are resized uniformly to reference scale, with rounded dimensions, and must be 8–512 pixels on each output axis. The compiler never stretches an aspect ratio or substitutes a full screenshot. Existing scale/search-work limits apply at the reference size; passing there does not promise arbitrary supported layouts.

At most sixteen anchors and four distinct train images may be selected. Their combined decoded source size is at most sixteen megapixels. Unknown keys, duplicate JSON keys, non-finite values, booleans in numeric fields, excessive nesting, invalid references and out-of-bounds boxes fail closed. The recipe is at most 128 KiB. Validation and held-out examples cannot provide templates; their pixels are never read during compilation. Demonstration requests are not executable and do not become routines.

## Local output and review

Compilation requires separate explicit consent to read the selected train images and persist their cropped derivatives. Choose crops that exclude chat, identifiers and private content. This is an export of image crops, unlike the metadata-only model-authoring report. No replay discovery, capture, model call, network request or automatic upload occurs.

Output is a new private local directory containing `proposal.json` and a `candidate` resource-pack directory. Assets are freshly encoded RGB PNG crops without source metadata. The candidate retains exact asset hashes, the original state kinds and `routines: []`. The receipt records selected example IDs and hashes, recipe/training metadata digests and fixed draft status. It never marks approval, native readiness or held-out evaluation complete. `persistent_images` is explicitly true because crops are exported; `held_out_used`, `approved`, `live_readiness`, `native_input`, `screen_capture` and `model_training` remain false.

```sh
uv run --locked python -m afk_grinder --compile-training /path/to/training.json --crop-recipe /path/to/recipe.json --fixture-directory /path/to/dataset --compile-output /path/to/new-proposal --compile-consent
```

The input is a standalone strict training packet. For model-authored data, review `report.packet` from the authoring report and save that packet separately; the outer authoring report is not a training packet. Review the crop recipe separately. No model output can select a source outside its permitted train examples or change the original state's protected kind through a recipe.

Only selected source images are hash/format/dimension-checked through the existing fixture loader. Initial decoding and crop generation run in a disposable worker with a sixty-second process deadline. Before exporting, the parent independently reloads those same hash-checked train files and rebuilds the deterministic crops, then requires exact candidate asset and manifest bytes plus receipt metadata. A child-supplied image with a rewritten hash cannot establish its own source. Parent work has the same image/count/search limits; the worker deadline is not a hard end-to-end wall-clock bound on this additional verification. This subprocess is not an operating-system sandbox. Output uses new files only, POSIX directory mode 0700 and file mode 0600; Windows privacy follows the chosen directory's ACLs. A failed export may leave an incomplete private directory without `proposal.json`; it is never reported as a successful proposal and a retry cannot overwrite it.

Review the images, recipe, provenance and state definitions, then evaluate separate validation and held-out fixtures through the existing [pack evaluator](PACK_EVALUATION.md). A compiled candidate may still match the wrong screen. Read-only Setup selection is not approval for input or a supported game profile.

## Original synthetic example

From a source checkout, create a new local example directory:

```sh
uv run --locked python -m tools.make_training_demo --destination /tmp/afk-training-demo
uv run --locked python -m afk_grinder --compile-training /tmp/afk-training-demo/training.json --crop-recipe /tmp/afk-training-demo/recipe.json --fixture-directory /tmp/afk-training-demo/fixtures --compile-output /tmp/afk-training-proposal --compile-consent
```

Both destination names must be unused. The demo contains four original train images, a validation example and nine held-out examples with synthetic safety labels and deliberate conflicts. It contains no game artwork or private screenshots. Its candidate can be checked separately with the optional pinned recognition dependency:

```sh
uv run --locked --extra recognition python -m afk_grinder --evaluate-pack /tmp/afk-training-proposal/candidate --training-packet /tmp/afk-training-demo/training.json --fixture-directory /tmp/afk-training-demo/fixtures --fixture-report /tmp/afk-training-held-out.json --fixture-consent
```

Static synthetic results are evidence of the conversion and evaluator plumbing, not actual Adopt Me accuracy, temporal stability, routine approval or native readiness.
