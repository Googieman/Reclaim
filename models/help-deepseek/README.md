# RECLAIM help model bundle

This directory contains metadata for the optional `reclaim-help-deepseek`
documentation assistant. It does not contain model weights. The GGUF artifact is
downloaded to an operator-selected directory outside the repository and verified
against `manifest.json` before use.

The candidate is `DeepSeek-R1-Distill-Qwen-1.5B` converted to GGUF Q4_0 by
ggml-org. It is an advisory documentation model, not an investigator, not a
business-state writer, and not a financial-action executor. The profile is
disabled until the help quality, resource, and authenticated gateway gates pass.

```powershell
pwsh ./scripts/models/prepare_help_model.ps1 `
  -ArtifactDirectory 'D:\reclaim-model-artifacts\help-deepseek'
```

Do not place the resulting file under this checkout, commit it, expose the
llama.cpp port publicly, or enable the profile without a reviewed deployment
decision.
