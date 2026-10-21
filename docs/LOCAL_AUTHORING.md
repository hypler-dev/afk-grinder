# Local multimodal draft authoring

Authority: [intent.md](../intent.md). This optional command turns explicitly selected training examples into an untrusted training-packet draft. It does not control Roblox, install a resource pack, fine-tune weights or approve its own output. The deterministic movement and recognition paths do not require an LLM.

## Prepare an existing local model

Choose and install a vision-capable model separately, review its license, and record its exact installed tag and SHA-256 digest. Model setup and performance evaluation remain separate work; the application never starts Ollama, pulls weights, changes its configuration or falls back to cloud inference. No real model has been benchmarked through this command yet.

Ollama must already be running locally with cloud features disabled. Its [official FAQ](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features) documents `OLLAMA_NO_CLOUD=1` or `disable_ollama_cloud` in its server configuration, followed by a restart. The command checks `GET /api/status` and requires `cloud.disabled: true` before sending an image. An unsupported status endpoint fails closed.

The API contract was inspected in official Ollama v0.40.6, commit [`2476d5e`](https://github.com/ollama/ollama/tree/2476d5ead197abe04629651028f83d48dc75d2b2). Its [client](https://github.com/ollama/ollama/blob/2476d5ead197abe04629651028f83d48dc75d2b2/api/client.go) exposes cloud status, and its [response types](https://github.com/ollama/ollama/blob/2476d5ead197abe04629651028f83d48dc75d2b2/api/types.go) expose remote-model metadata. This source inspection is not a real-model compatibility or performance result.

Only literal `127.0.0.1` is contacted, on port 11434 by default. There are no URL, proxy, redirect, authentication, cloud or retry options. The command checks the selected installed model's exact digest before and after generation, requires local GGUF metadata and completion/vision capabilities, and rejects remote-model metadata. Tags must be explicit; implicit and `latest` tags are rejected. Copy the tag and digest from your own installed-model inventory.

These checks rely on an honest, user-controlled local Ollama service. They are not an OS network sandbox or cryptographic attestation of model execution.

## Select examples and request a draft

Prepare a valid [training packet](TRAINING_PACKETS.md) and its local fixture directory. Select one to four example IDs whose split is `train`. Validation and held-out examples cannot be selected. Replay images are never discovered or reused automatically.

```sh
uv run --locked python -m afk_grinder --author-local /path/to/training.json --fixture-directory /path/to/dataset --author-model gemma4:e2b --author-digest REPLACE_WITH_YOUR_64_CHARACTER_INSTALLED_SHA256 --author-example gameplay-001 --author-output /path/to/new-proposal.json --author-consent
```

Replace the illustrative model tag and digest with your selected installed model. Repeat `--author-example` for each chosen training example. The output must be a new file; existing files are never overwritten.

Consent is specific to reading these fixtures and sending their in-memory derivatives to the local model. Each selected image must match its declared hash, format and dimensions. It is decoded, reduced proportionally to at most 960 pixels on either edge, and re-encoded as JPEG without source metadata. Only these JPEGs and bounded authoring context enter the request; fixture paths, hashes, nonselected example records and held-out images do not enter the prompt. Source images are not changed or copied to the output.

The disposable worker has a 60-second process deadline; HTTP operations share a 50-second budget. Generation requests use two CPU threads, a 4096-token context, a 1024-token output cap and `keep_alive: 0`. Installed-model files are capped at 8 GiB. File size and API options are not a loaded-RAM or GPU-memory limit; benchmark the chosen runtime and hardware separately. Closing the client does not guarantee that another process immediately unloads all model resources.

## Review the result

A successful file has `ok: true` and `report.packet`, which is a schema-validated `afk-grinder-training` draft. The report also records the selected IDs, canonical input-metadata digest, selected model identity and checked runtime metadata. It saves neither images, prompts nor an unvalidated model reply. POSIX output permissions are restrictive; Windows permissions depend on the selected directory's ACLs.

The model may add new states, propose labels for selected train examples and request bounded semantic demonstrations using those examples. It cannot rewrite existing states, game identity, paths, hashes, dimensions, splits, origins, nonselected labels or existing demonstrations. A selected transaction example cannot be downgraded to another kind. Login-oriented labels, raw input/code requests, extra fields, invalid references and unsafe capabilities fail validation.

All approval, runtime-pack, native-input, capture, image-persistence, weight-training and held-out-prompt flags remain false. A valid draft can still be wrong. Human review and separate held-out evaluation are required; there is no automatic pack conversion, activation or live routine path.

After review, save `report.packet` as a standalone training packet. The separate [crop compiler](TRAINING_COMPILER.md) can combine it with a reviewed train-only crop recipe to produce an unapproved recognition candidate. That export requires separate consent to persist image crops; it never inherits the metadata-only authoring consent or turns demonstration requests into routines.

Failures save only a fixed code such as `cloud_required`, `model_changed`, `fixture_invalid`, `proposal_invalid` or `timeout`. Native/server exception text and raw replies are not logged. A failed or timed-out proposal never becomes a partial success.

## Evidence boundary

Synthetic tests exercise a real disposable Python worker against a loopback fake Ollama protocol, including successful authoring and refusing image transmission when cloud is enabled. They do not run a VLM or establish model quality, resource use, actual Adopt Me labels, care completion, native calibration or cross-machine inference compatibility. See [plan.md](../plan.md) for exact validation and build evidence.
