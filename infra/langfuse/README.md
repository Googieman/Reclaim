# Langfuse boundary

The model trace sink receives redacted structured inputs, provider/model metadata,
token/cost metadata when available, and correlation identifiers. Provider keys are
injected at runtime through Vault; no key or raw evidence is stored here.
