# Dashboard Help Chat with Private 1.5B Model

## Goal

Make the existing RECLAIM documentation-help flow available as a small,
bottom-right chatbot on every dashboard route, backed by the checked-in
DeepSeek-R1-Distill-Qwen-1.5B Q4_0 candidate model and deployed through the
existing Railway web/API services plus a new private model service.

## Scope

- Keep the existing `HelpChatPanel`, `/help/chat` contract, reviewed-document
  retrieval, citations, and advisory-only response boundary.
- Change the closed UI entry point from a navigation-footer panel to a fixed,
  keyboard-accessible bottom-right chat icon. Opening it reveals the current
  question form, loading/cancel/retry states, safe abstention states, answer,
  and reviewed source links.
- Support questions about the dashboard, RECLAIM workflows, safety boundaries,
  contracts, and reviewed project documentation. The assistant must not inspect
  case records, approve actions, execute connectors, mutate business state, or
  invent unsupported answers.
- Deploy the `reclaim-help-deepseek` profile using the manifest-pinned
  `DeepSeek-R1-Distill-Qwen-1.5B-Q4_0-GGUF` artifact. Model weights remain
  outside Git, are checksum-verified, and are mounted from private Railway
  storage.
- Enable the authenticated help route in the API and connect it to the private
  model service through the existing OpenAI-compatible gateway boundary.

## Architecture and data flow

1. A reviewer opens the fixed help icon on the public Next.js dashboard.
2. The browser submits a relative `/help/chat` request with the existing
   bearer identity and tenant header; no public model endpoint is exposed.
3. Next.js rewrites the request to the Railway API service over the configured
   internal service address.
4. The API validates identity and reviewer role, normalizes the question,
   retrieves only reviewed passages from `docs/help/index.json`, and sends the
   bounded question/passages payload to the private model gateway.
5. The gateway calls the private llama.cpp `model-help` service using a
   deployment-only API key. The model service has no web UI, no public domain,
   no tools, and concurrency one.
6. The API validates the model answer and citations. Unsupported, malformed,
   private-reasoning, timed-out, or unavailable responses become explicit safe
   abstentions.
7. The frontend renders the answer and reviewed source links without persisting
   a transcript.

## Deployment configuration

- Public web service: existing Railway `marvelous-truth` service, built from
  `frontend/Dockerfile`.
- API service: existing Railway `Reclaim` service, with help enabled only after
  the private model service passes readiness.
- Model service: new private Railway service built from
  `infra/model-help/Dockerfile`, port `8080`, health path `/health`, and a
  persistent volume mounted at `/models`.
- Model artifact: `deepseek-r1-distill-qwen-1.5b-q4_0.gguf`, using the SHA-256
  recorded in `models/help-deepseek/manifest.json`.
- Secrets: `MODEL_API_KEY`, the API-to-model credential, and any model artifact
  retrieval credential are Railway secrets only; none are checked in or shown
  in logs.
- API environment: enable `RECLAIM_HELP_ENABLED`, set the
  `reclaim-help-deepseek` profile, point `RECLAIM_HELP_API_BASE` at the private
  model endpoint, and provide the gateway credential.
- Live refunds, cancellations, payments, and other merchant actions remain
  disabled.

## Testing and acceptance

- Add or update frontend tests proving the closed control is a fixed,
  keyboard-accessible chat icon and the open panel preserves the existing
  bounded help form and safe states.
- Add or update contract/security tests proving the enabled route still
  requires bearer identity, tenant scope, reviewer role, bounded input, and
  rejects case context.
- Run the focused help-chat backend/frontend suites plus frontend typecheck,
  lint, and production build.
- Verify the model service health endpoint, API readiness, and one authenticated
  documentation question from the public dashboard. Verify an unsupported
  question returns a safe abstention and that no model or action endpoint is
  publicly exposed.
- Record deployment smoke evidence without claiming full production
  qualification; the remaining hosted final-round gates stay open.

## Non-goals

- No general-purpose autonomous agent, web search, arbitrary tool use, case
  investigation, business-state mutation, or action execution.
- No model weights committed to the repository.
- No public domain for the model service.
- No changes to live-action enablement or financial execution policy.
