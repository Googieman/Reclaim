# Canonical replay variants

Each JSON file in this directory declares one deterministic deviation from
`../incident.json`. The files contain only fixture metadata and expected
outcomes; they do not contain credentials, provider secrets, held-out cases, or
instructions to perform a real action. `backend/replay/variants.py` applies the
declared deviation to an isolated copy of the canonical replay result.
