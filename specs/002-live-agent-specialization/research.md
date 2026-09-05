# Live Agent Specialization Research

**Date**: 2026-09-02

## Decision: Reuse the existing bounded agent boundary

**Decision**: Keep LangGraph as the finite harness, LiteLLM as the provider-neutral adapter, `build_safe_model_context` as the redaction/context boundary, the strict parser and typed proposal boundary, deterministic US2 analysis, and the existing replay fallback.

**Rationale**: The audit found these components already enforce schema versions, tenant/case scope, read-only tool limits, evidence/reference validation, deterministic uncertainty retention, and no remote side-effect channel. The defect is product/runtime reachability, not a missing agent framework.

**Alternatives considered**: Replacing LangGraph with a new framework would duplicate safety controls and violate the approved architecture. Calling a model directly from the frontend would bypass Temporal/API boundaries and is rejected.

## Decision: Represent fresh model execution separately from merchant action mode

**Decision**: Keep the existing provider `live`/`replay` contract values internally, but expose `fresh_agent` as the public analysis execution mode and retain a separate action-environment value (`simulator`, `test_mode`, or `live_merchant`).

**Rationale**: A fresh model call is not a financial execution. Reusing the existing `live` label without a distinct public analysis mode would make the UI and API ambiguous.

**Alternatives considered**: Renaming the shared `ProviderMode` contract would touch existing replay contracts and protected shared boundaries; a feature-local public mode avoids that incompatible change.

## Decision: Use a logical model-profile registry

**Decision**: Resolve `reclaim-specialist`, `reclaim-baseline`, and optional `reclaim-cloud-fallback` profiles to the existing LiteLLM adapter. Endpoint/base URL and credentials come from environment/configuration, never from model input or frontend data.

**Rationale**: One provider interface makes local specialist, base open-weight, and configured cloud providers interchangeable and allows provenance to record what actually ran.

**Alternatives considered**: Hard-coding a Soup HTTP client in LangGraph would couple the harness to training/serving implementation and bypass LiteLLM.

## Decision: Generate examples from deterministic analysis, not hidden reasoning

**Decision**: Build JSONL chat examples from the existing deterministic case context, attribution, uncertainty, exposure, and proposal inputs. Targets contain concise rationales, references, typed action proposals, and refusal records only.

**Rationale**: Deterministic services remain financial/policy authority, and hidden chain-of-thought is neither required nor appropriate for the training artifact.

**Alternatives considered**: Manually maintained opaque JSONL is rejected because it cannot reproduce provenance or leakage checks. Teacher-generated targets may supplement data only when independently validated; they are not ground truth.

## Decision: Split groups before overlays and keep held-out labels sealed

**Decision**: Assign entity/customer/time groups to development, validation, or held-out before any deterministic variations. The builder consumes only development cases for training and writes held-out metadata/checksums without reading held-out answers.

**Rationale**: This prevents leakage through related identities, time adjacency, or augmented fixtures and makes the evaluator's held-out boundary inspectable.

**Alternatives considered**: Random row splitting is rejected because the same merchant/customer/event family can appear in multiple rows.

## Decision: Soup CLI workflow and hardware gate

**Decision**: The current documented CLI is installed as `soup-cli` in an isolated Python 3.12 environment. The supported workflow is `soup doctor`, optional `soup data doctor`, `soup train --config`, `soup eval`, and `soup serve --model`. Initial training is SFT, preferably LoRA/QLoRA; DPO/GRPO/distillation are skipped unless separately justified.

**Rationale**: The official documentation says the current release is 0.72.4, Python 3.10–3.12 is supported, and resident 7B QLoRA generally wants 8 GB+ VRAM. This host exposes Python 3.12 and an RTX 3050 Laptop GPU with 4096 MiB, so the model choice and whether SFT is possible must follow `soup doctor`, not assumption. The docs describe `training.stream_layers: true` as a 4 GB beta option to try only if the installed version supports it.

**Alternatives considered**: Installing training dependencies into the production `.venv` is rejected. Claiming a fine-tuned checkpoint from a config-only run is rejected. GRPO is rejected for the first slice because there is no measured need or safe reward/hacking study.

**Authoritative references**:

- [Soup CLI getting started](https://trysoup.dev/docs/getting-started)
- [Soup CLI training methods](https://trysoup.dev/docs/training)
- [Soup CLI reference](https://trysoup.dev/docs/cli-reference)
- [Soup fine-tune doctor](https://trysoup.dev/docs/fine-tune-doctor)

## Decision: Do not add a new architecture decision record

This feature records implementation choices here but does not change data ownership, action authority, workflow ownership, or replay semantics. Existing FS-001 ADRs remain unchanged. If implementation later requires a material architecture change, stop and add an explicitly reviewed feature-local decision before coding.

## Observed pre-implementation environment

- `soup` executable: not installed at audit time.
- Project `.venv`: Python 3.12.13 with existing LangGraph 0.2.60 and LiteLLM 1.55.8.
- System Python: 3.13.14, outside the current Soup support range.
- GPU: NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB, driver 610.62.
- RAM: approximately 16 GiB.
- No PyTorch, Transformers, PEFT, or TRL in the system Python environment.

These are observations, not training results. The training phase remains gated on the isolated Soup doctor and actual command outcomes.
