# RECLAIM Agent Specialization

This directory contains the reproducible data, evaluation, Soup configuration, and
observed-run manifests for the RECLAIM advisory agent. Generated rows and model
checkpoints are ignored; source manifests, configs, and reports remain reviewable.

## Safety and truthfulness

The model receives bounded, redacted, untrusted evidence and emits advisory structured
analysis only. It does not calculate authoritative money, approve proposals, execute
actions, or access credentials. `reclaim-specialist` is a logical profile; it is not
considered trained until an observed Soup training run produces a checkpoint and an
evaluation report.

The current host audit found Python 3.12.13 in the project environment, an NVIDIA RTX
3050 Laptop GPU with 4096 MiB, and approximately 16 GiB RAM. Soup was not installed at
audit time. Update those facts only from observed `soup doctor` output.

## Workflow

```powershell
python -m venv training/.venv
training/.venv/Scripts/python.exe -m pip install "soup-cli[train]"
training/.venv/Scripts/soup.exe doctor
.venv/Scripts/python.exe training/reclaim/scripts/build_dataset.py --source tests/fixtures/canonical/incident.json --output training/reclaim/data/generated
.venv/Scripts/python.exe training/reclaim/scripts/validate_dataset.py --dataset training/reclaim/data/generated --manifest training/reclaim/manifests/dataset.json
```

Run the base evaluation before any training. Use the documented Soup `sft` task only
after data validation and a successful environment gate. DPO, distillation, and GRPO
are not enabled by default because this repository does not yet contain verified human
preference pairs or a measured need for reinforcement tuning.

## Observed local run

On 2026-09-02, the isolated environment installed Soup 0.73.3 and `soup doctor`
passed. Soup detected an NVIDIA RTX 3050 Laptop GPU, but the isolated Torch build
was CPU-only. After the data doctor found and the config corrected a 3,476-token
truncation risk, the real 2-step SFT run completed against the one development row
with `HuggingFaceTB/SmolLM2-135M-Instruct`. The adapter and trainer telemetry are
recorded in `manifests/training-run.json`; this is not a fraud-quality benchmark and
the profile remains `DON'T SHIP` because validation and held-out data are absent.

The loopback serving probe is recorded in `manifests/serving.json`. The adapter
served health/models successfully, but the tiny one-case model did not emit a valid
RECLAIM response under the probe cap, so it is not used as a qualified default.

## Qualification gates

Evaluation metadata may be structurally valid while remaining unqualified. Model
selection requires the sealed held-out minimum (currently 100 cases), at least 25%
no-compromise/false-alert cases, and at least 30% mixed legitimate/malicious cases
among compromised cases. Reports must retain the dataset/manifest checksum, split,
evaluator, environment, model profile, confidence-interval seed, and observed sample
size. Missing or invalid model outputs, missing drift baselines, mismatched manifests,
and unverified checkpoints fail closed to `DON'T SHIP`.

The checked-in corpus has zero held-out cases and the observed one-case adapter did
not produce a strict RECLAIM response, so both remain explicitly `DON'T SHIP`; no
rows or metrics are fabricated to satisfy a gate. Use the dataset validator before
training and the promotion command only with two reports from the same sealed
manifest:

```powershell
python training/reclaim/scripts/validate_dataset.py --dataset training/reclaim/data/generated --manifest training/reclaim/manifests/dataset.json
python training/reclaim/scripts/promotion.py --base training/reclaim/evals/base.json --specialist training/reclaim/evals/specialist.json --output training/reclaim/evals/comparison.json --training-manifest training/reclaim/manifests/training-run.json
```

Authoritative Soup references: [getting started](https://trysoup.dev/docs/getting-started),
[training](https://trysoup.dev/docs/training), and
[CLI reference](https://trysoup.dev/docs/cli-reference).
