# Small local multimodal model review

Authority: [intent.md](../intent.md). Reviewed October 20, 2026. This is a model shortlist and evaluation plan, not a local performance result or approval to execute generated instructions.

## Recommendation

Start the authoring evaluation with **Qwen3.5-4B using a 4-bit local build**. Compare it with Gemma 4 E4B on the same held-out game examples. Use Qwen3.5-2B as the constrained-memory candidate and Gemma 4 E2B as the smaller Gemma candidate. Ministral 3 3B is another compact vision/instruction baseline. All support image input; no audio model is required for this application.

| Candidate | Evidence relevant to this application | Initial role |
| --- | --- | --- |
| Qwen3.5-4B | The publisher reports OCRBench 85.0 and ScreenSpot Pro 60.3, with text/image/video support and Apache-2.0 weights. | First screenshot-to-draft candidate |
| Qwen3.5-2B | The publisher reports ScreenSpot Pro 54.5 in non-thinking mode and OCRBench 85.4 in that mode. | Smaller fallback to benchmark |
| Gemma 4 E4B | Google documents image/UI/OCR capabilities; its reported MMMU Pro score is 52.6%, versus E2B's 44.2%. | Gemma quality challenger |
| Gemma 4 E2B | Google lists 2.3B effective parameters but 5.1B including embeddings. Effective parameter count is not the complete memory footprint. | Small Gemma baseline |
| Ministral 3 3B Instruct | Mistral documents a 3.4B language model plus 0.4B vision encoder, JSON output, and quantized deployment below 8 GB RAM/VRAM. | Compact alternative |

Sources: [Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B), [Qwen3.5-2B model card](https://huggingface.co/Qwen/Qwen3.5-2B), [Google Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4), [Ministral 3 3B model card](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512-BF16).

These are publisher-reported results, not an identical cross-model local test. Different prompts, runtimes, quantization and image processing can change results. The recommendation is an engineering inference from task relevance and footprint, not a claim that one model has already won on Adopt Me. None of the cited benchmark results establishes purchase/trade safety.

The development Mac was read as an Apple M1 Pro with 32 GiB RAM. This supports testing these candidates; simultaneous Roblox performance and peak model memory remain unmeasured. Windows and smaller-memory machines need their own measurements. An on-disk model size does not equal loaded RAM, vision-encoder memory, context cache or total application memory.

## Product boundary

The intended flow is selected examples → local multimodal model → draft training packet → strict validation → held-out evaluation → human review → a separately approved runtime pack. The model proposes labels, state descriptions and semantic capability requests. It receives no native input capability, shell, filesystem tool or approval authority. Prompts and model responses are untrusted data. The existing runtime pack still rejects routines; a training draft cannot silently enable them.

Regular execution uses the guarded deterministic input engine and local recognition. Model latency must never delay Stop, Escape, focus-loss cancellation or held-input cleanup. No model is required for the existing movement prototype.

Ollama supports [vision input](https://docs.ollama.com/capabilities/vision) and [JSON-schema outputs](https://docs.ollama.com/capabilities/structured-outputs). Local-only operation also requires controlling its cloud features: the [official FAQ](https://docs.ollama.com/faq) documents `OLLAMA_NO_CLOUD=1` or `disable_ollama_cloud`. A loopback endpoint alone does not prove that a selected model is local. Do not assume a cloud model becomes local because its API is reachable at localhost.

The local Ollama binary was found, but its server was not running during this review. No model was downloaded or executed, and no game screenshot was sent to a model. Model installation, exact digest/quantization selection, local-only configuration and a synthetic canary remain pending. Avoid mutable `latest` tags in a validated profile.

## Evaluation before selection

Use identical, consented examples and an untouched held-out split: clear gameplay, each approved popup, purchase/trade lookalikes, disconnect reasons, login/loading/unknown screens, overlapping windows, scaling and partially obscured buttons. Keep private captures out of source control. Replays are not automatically training data; export requires a separate explicit choice.

Measure state classification, protected/unknown rejection, exact OCR fields, proposed target bounds, valid packet rate, unsupported capability requests, cold-load time, median/p95 latency and peak RAM/GPU memory. Run on the actual Mac and representative Windows hardware while Roblox is open. A finite successful test suite is evidence, not a guarantee against every unknown overlay.

Start with prompting and labeled examples. Fine-tuning is a later milestone after the dataset and baseline failures justify it; it requires a chosen training framework, model/adapter provenance, resource limits and the same held-out comparison. The training packet's export helper prepares data only; it does not train, download or publish a model.
