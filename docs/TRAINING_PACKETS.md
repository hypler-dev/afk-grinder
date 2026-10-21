# Training packets

`afk-grinder-training` schema version 1 is a local, data-only proposal format for labeling game states and requesting semantic routine capabilities. It is separate from the existing `afk-resource-pack` v1 runtime recognition format. A training packet cannot install a runtime pack, start a routine, approve a routine, or change an input safety gate.

Every valid packet has `status: "draft"`. Model output, including a proposal from a local Gemma model, must pass the same parser and remains an untrusted draft. A valid JSON file does not prove that an asset exists, that its SHA-256, dimensions, origin, or provenance claims are correct, or that a game behavior is safe.

## Schema boundary

The root has exactly these keys: `format`, `schema_version`, `status`, `id`, `version`, `game`, `locale`, `reference_size`, `states`, `examples`, and `demonstrations`.

- `format` is `afk-grinder-training`; `schema_version` is `1`; `status` is only `draft`.
- IDs and capability requests are lowercase hyphenated slugs. `version` is `X.Y.Z`; `locale` is currently `en`.
- `game` has exactly `id`, `title`, and `place_id`. A place ID is `null` or one to twenty digits.
- `reference_size` and each example size are two positive integers no larger than 16 megapixels.
- A state has `id`, `kind`, and a control-character-free description up to 256 characters. Kinds are `gameplay`, `popup`, `transaction`, `loading`, `disconnected`, and `unknown`.
- An example has `id`, canonical ASCII path `examples/<id>.webp|jpg|png`, lowercase SHA-256, dimensions, `state_id`, `split`, and `origin`. Splits are `train`, `validation`, and `held_out`; origins are `synthetic` and `manual`. The parser reads no image bytes. The sample's `synthetic` metadata is not an image, does not imply that any asset exists, and does not pass a packet.
- A demonstration has state IDs, a semantic capability-request slug, referenced example IDs, duration from 1 to 30,000 ms, and retry limit 0 to 2. Capability names are labels only; executable input/code terms are rejected. Transaction and unknown states cannot participate in a capability request.

The parser rejects duplicate JSON keys, non-finite and floating JSON numbers, unknown or missing fields, booleans in numeric fields, control characters, unsupported text, depth above 12, JSON above 1 MB, invalid references, duplicate IDs, and an identical SHA-256 across different splits. It also rejects login/authentication-oriented training labels and requests. It does not access files, networks, models, or input APIs.

## Draft workflow

1. Create local manual example metadata. Keep screenshots and replay images out unless they are separately selected and consented.
2. A local Gemma proposal may add labels, descriptions, and semantic requests. It has no execution or approval authority.
3. Run `parse_training_packet(text)` for schema checks.
4. Review held-out examples separately. Held-out items never enter `fine_tuning_records`.
5. A separately approved future compiler may translate reviewed data into a restricted runtime pack. This module provides no compiler or approval path.

The current runtime evaluator is a separate, explicit-consent path. Use the
[pack evaluation guide](PACK_EVALUATION.md) for the CLI and evidence boundary. It reads only the
selected packet examples, defaults to `held_out`, and reports metadata such as
labels, scores, boxes, and confusion counts. It does not emit image bytes,
fixture paths, or native text. Its disposable child has a 120-second deadline but is not an
operating-system sandbox. Static candidate results are unstabilized; blocked
protected states remain blocked.

Qwen3.5-4B is the current local proposal-authoring evaluation candidate. Gemma 4 E4B is the quality challenger, and Gemma 4 E2B remains a smaller candidate; none is a selected runtime. See [local model evaluation](LOCAL_MODELS.md) for candidate evidence and source links. The training-packet parser does not call Ollama, require a model runtime, download a model, send cloud requests, or load image pixels. The separate fixture evaluator loads selected image pixels only with explicit fixture consent.

`fine_tuning_records(packet, consent=True)` returns JSON text records for `train` and `validation` metadata only. It emits each relative file reference and SHA-256 claim, never image bytes, and requires explicit caller consent. It is not a fine-tuning runtime. Eventual fine-tuning work still needs a separately selected local runtime plus benchmark, license, hardware/resource, privacy, and held-out-evaluation gates.
