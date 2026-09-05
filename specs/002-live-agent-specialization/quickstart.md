# Fresh-Agent Specialization Quickstart

This guide is evidence-oriented. Commands must be run in the repository's existing Python 3.12 environment for backend checks and in the isolated training environment for Soup. No command in this guide enables live financial actions.

## 1. Inspect and validate the source state

```powershell
git status --short
.venv/Scripts/python.exe -m pytest tests/unit/test_agent_gateway.py tests/unit/test_analysis_output_parser.py
```

Confirm the protected dirty paths remain untouched. REPLAY regression must still pass:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_canonical_replay.py tests/unit/test_mode_selection.py
```

## 2. Prepare the isolated Soup environment

```powershell
python -m venv training/.venv
training/.venv/Scripts/python.exe -m pip install "soup-cli[train]"
training/.venv/Scripts/soup.exe doctor
```

Record the actual version, Python, GPU/VRAM, CUDA, RAM, and supported backend in `training/reclaim/manifests/environment.json`. On a host that cannot meet the installed Soup requirements, stop only the training phase and record the exact output; do not claim a trained checkpoint.

## 3. Generate and validate data

```powershell
.venv/Scripts/python.exe training/reclaim/scripts/build_dataset.py --source tests/fixtures/canonical/incident.json --output training/reclaim/data/generated
.venv/Scripts/python.exe training/reclaim/scripts/validate_dataset.py --dataset training/reclaim/data/generated --manifest training/reclaim/manifests/dataset.json
```

The output must show actual row counts, split counts, class balance, zero invalid references/actions, zero secret fields, and a held-out seal. Only approved development rows may be passed to training.

## 4. Establish baseline before training

```powershell
.venv/Scripts/python.exe training/reclaim/scripts/evaluate.py --profile reclaim-baseline --manifest training/reclaim/manifests/dataset.json --output training/reclaim/evals/base.json
```

The evaluator may use a deterministic provider stub in CI; that is a harness check, not a base-model metric. Any real model metric must identify its model artifact and environment.

## 5. Soup data doctor and SFT

```powershell
training/.venv/Scripts/soup.exe data doctor training/reclaim/data/generated/train.jsonl --model <selected-open-weight-model> --output training/reclaim/manifests/soup-data-doctor.json
training/.venv/Scripts/soup.exe train --config training/reclaim/configs/reclaim-sft.yaml --yes
```

The config records the selected base model, SFT/LoRA or QLoRA settings, seed, data path, max length, and ignored output directory. Do not run DPO/GRPO without a documented data-quality decision. Checkpoint files are external/ignored artifacts.

## 6. Evaluate and serve only an observed artifact

```powershell
training/.venv/Scripts/soup.exe serve --model <observed-checkpoint> --host 127.0.0.1 --port 8003
.venv/Scripts/python.exe training/reclaim/scripts/evaluate.py --profile reclaim-specialist --manifest training/reclaim/manifests/dataset.json --model <observed-checkpoint> --output training/reclaim/evals/specialist.json
```

The local endpoint must be reachable through the existing LiteLLM adapter. If no checkpoint exists, configure the profile as unavailable and run the provider-failure tests; do not point `reclaim-specialist` at a replay fixture.

## 7. Run the fresh-agent path

With the backend configured for an explicit local specialist endpoint and development-only simulator environment:

```powershell
$env:RECLAIM_FRESH_AGENT_ENABLED = "true"
.venv/Scripts/python.exe -m uvicorn api.main:app --app-dir backend --port 8000
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/tenants/tenant-canonical-demo/cases/case-canonical-demo-001/agent-runs -ContentType application/json -Body '{"provider_profile":"reclaim-specialist"}'
```

The response must show `execution_mode: fresh_agent`, provider/model provenance, a new run/checksum, and no replay label. Action controls remain downstream and disabled/gated by existing policy/approval/Action Gateway state.

## 8. UI and replay proof

Open the canonical case in the operator UI. Verify that REPLAY remains recorded-fixture/read-only and that Fresh Agent shows a distinct model-run status and provider/model provenance. Run the replay button separately and confirm it does not increment the fresh provider call count.

## Evidence to retain

Retain the dataset manifest/validation report, Soup doctor output, exact SFT config, baseline/specialist comparison, local endpoint smoke result, fresh-agent API response, replay regression result, safety-test output, and final `git diff --check`. Label synthetic/hybrid evaluation and report all unavailable or unmeasured items.
