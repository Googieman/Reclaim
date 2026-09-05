# RECLAIM Operator UI Plan

## 1. Status

- **Status:** Approved
- **Approval date:** 2026-09-02
- **Planning HEAD:** `9170e4e9c5fc4ce15ae5997368c937ea5659e364`
- **Scope:** T122-T124 only
- **Implementation state:** Not started
- **Authority:** The constitution, FS-001 specification, contracts, data model, ADRs, and security boundaries remain authoritative. This document governs presentation and interaction, not business semantics.

## 2. Product Surface

The primary surface is the authenticated case workspace at `frontend/src/app/cases/[caseId]/page.tsx`. It joins investigation, exposure, deterministic decision authority, human approval, action lifecycle, verification, escalation, and immutable provenance around one tenant-scoped case.

This is not an executive dashboard. T122-T124 may provide a compact application shell and case navigation, but must not create unrelated analytics pages, fake metrics, or inert destinations.

## 3. User and Operational Context

Merchant fraud, risk, and incident-response operators use RECLAIM during high-stakes review in dim or mixed-light environments and for long desktop sessions. They need rapid comprehension without losing evidence, uncertainty, financial authority, or separation of duties.

Priority is desktop investigation and decision-making, then tablet review/approval, then mobile status and decision summary. Operators may be rushed or focused for long periods; the interface must remain calm, explicit, and keyboard-efficient.

## 4. Design Thesis

> RECLAIM is a dark, high-density incident command workspace for fraud-loss containment. It combines investigative chronology, financial exposure, deterministic policy, human approval, action lifecycle, verification, and immutable provenance in one operational case surface.

The approved visual reference informs compact enterprise shell proportions, panel hierarchy, spacing rhythm, table discipline, and quiet navigation. It does not authorize copying branding, assets, executive KPI grids, charts, or generic security-console styling.

## 5. Design Principles

1. **The case is the workspace.** Every region is a perspective on one evolving incident.
2. **Investigation precedes decision.** The timeline/table hybrid is the main visual spine; containment authority remains persistent but secondary.
3. **Authority is explicit.** Advisory analysis, deterministic policy, approval, gateway execution, reconciliation, verification, escalation, and terminal state never collapse into one status.
4. **Uncertainty is honest.** Uncertain attribution, UNKNOWN execution, and inconclusive verification are separate states and never resemble softened success or weak maliciousness.
5. **Remaining risk leads.** Remaining Exposure is the dominant financial value; all amounts remain backend-authoritative integer minor units with explicit currency.
6. **Mode is structural.** LIVE and REPLAY are unmistakable without relying on color.
7. **Density comes from alignment.** Never obtain density through artificially tiny text, compressed line height, or unstructured clutter.

## 6. Information Architecture

Global destinations, shown only when backed by a real route:

- Case Queue
- Investigations
- Active Containment
- Approvals
- Escalations
- Replay
- Evaluation
- Audit
- Settings

Case workspace regions:

- Persistent case identity and mode
- Incident Investigation
- Evidence and attribution detail
- Decision / Containment
- Verification and escalation
- Audit Trace / Provenance

Relationships/graph exploration is a secondary timeline toggle or drill-down. It is never the default or an authoritative source.

## 7. Global Layout

- **Navigation rail:** 48px collapsed, approximately 208px expanded. Active state uses a quiet surface fill plus icon/label emphasis; no colored side stripe.
- **Top bar:** 40-44px. Contains RECLAIM identity, tenant/merchant selector, global search, global mode statement, notifications, operator identity, and environment.
- **Case header:** 52-56px. Contains case ID, merchant, state, owner, severity, last authoritative refresh, and permanent mode badge.
- **Workspace gutters:** 12px desktop; 8px constrained layouts.
- **Panels:** continuous rectangular operational surfaces, 4-8px radius, thin borders, no decorative shadow.
- **Desktop split:** approximately 66% investigation and 34% decision, with decision width never below the readable exact-action threshold.
- **Audit region:** persistent bottom bar expanding to a non-modal trace panel.

Environment, run mode, provider availability, and live-action enablement are displayed as separate facts.

## 8. Case Workspace Layout

```text
┌────┬──────────────────────────────────────────────────────────────────┐
│    │ RECLAIM · Merchant · Search · LIVE/REPLAY · Operator · Env      │
│ N  ├──────────────────────────────────────────────────────────────────┤
│ A  │ Case ID · Merchant · State · Owner · Severity · Updated · Mode  │
│ V  ├─────────────────────────────────────────┬────────────────────────┤
│    │ Incident Investigation                   │ Decision / Containment │
│    │                                          │                        │
│    │ Timeline/table filters                   │ Remaining Exposure     │
│    │ Time · Event · Attribution · Evidence    │ Exposure ledger        │
│    │ Financial impact · Provenance            │ Containment state      │
│    │ Expandable rationale/source detail       │ Deterministic policy   │
│    │                                          │ Exact action packet    │
│    │ Relationship drill-down (secondary)      │ Approval               │
│    │                                          │ Lifecycle              │
│    │                                          │ Next human decision    │
│    ├─────────────────────────────────────────┴────────────────────────┤
│    │ Audit Trace — immutable · Narrative · Technical Chain           │
└────┴──────────────────────────────────────────────────────────────────┘
```

The investigation region scrolls independently on desktop. The decision region is sticky within the workspace and always preserves the next-human-decision area. Expanding audit must not hide the action identity currently under review.

## 9. Timeline Design

The timeline is a semantic table aligned to a chronological rail. Default columns are effective timestamp, event/resource, attribution, confidence/rationale, evidence references, financial impact, and provenance.

Each row supports keyboard expansion for source timestamps, provider identifiers, conflicting source events, uncertainty reasons, model/rules versions, rationale, and evidence links. Sticky headers and compact row separators support long cases. Filtering covers attribution, event type, source, evidence completeness, financial impact, and time range. Filtered scope is always stated and never silently changes case totals.

Design for empty, partial, typical, and long histories. Pagination/windowing must follow the eventual API contract; the UI must not fabricate client-only completeness.

## 10. Attribution Design

- **Malicious:** explicit `Malicious` label, critical icon, controlled red treatment.
- **Legitimate:** explicit `Legitimate` label, verified-person/check icon, controlled green treatment.
- **Uncertain:** explicit `Uncertain` or `Unresolved attribution` label, split-diamond/question structure, amber treatment, and a reason such as “Evidence does not support a conclusion.”

Attribution confidence is advisory and shown beside method and version. It never authorizes action. Uncertain is not displayed as low-confidence maliciousness. Color is never the sole carrier.

## 11. Financial Exposure Design

Remaining Exposure is the largest value and first item in the decision region. Recoverable Exposure is second. Contained Value, Gross Exposure, and Irreversible Loss are supporting aligned rows rather than equal cards.

Rules:

- Format backend integer minor units deterministically.
- Always show currency.
- Separate currencies; never infer conversion or a cross-currency total.
- Expose calculation version and source references on demand.
- Preserve meaningful zeros.
- Never derive authoritative values from model prose or filtered timeline rows.
- Use no gauge, donut, security score, decorative trend, or trading-style treatment.

## 12. Policy Design

Policy appears as a distinct deterministic decision block containing result, evaluated conditions, immutable version, evaluator version, timestamp, approval rule, and reason. `Allow`, `Deny`, `Approval required`, and `Escalate` remain distinct.

`Approval required` uses a consequential amber/ochre treatment with an approval-authority icon and full text. It must not resemble ordinary informational blue. A policy-version change marks the proposal stale and prevents approval/execution until the backend re-evaluates it.

## 13. Approval UX

Approval is a persistent decision region, not a modal-first flow. The exact-action packet shows action type, exact target, amount/currency, evidence/rationale, advisory confidence, reversibility, customer impact, current resource state, policy decision/version, proposer, required approver role, and stable action identity.

Submission is permitted only to an authorized approver distinct from the proposer. A final confirmation dialog may repeat the exact packet and explain: approval permits backend eligibility; it does not prove execution or success. Reject uses equally clear language without manipulative styling.

States include not required, required/absent, pending, approved, rejected, expired, revoked, self-approval forbidden, stale policy, changed resource, permission denied, submitting, recorded, and recorded-but-workflow-acknowledgement-pending.

## 14. Action Lifecycle UX

Use a compact ordered ledger:

`Proposed → Policy evaluated → Approval → Execution → Reconciliation → Verification`

Terminal outcome appears immediately after Verification rather than as an implied seventh success step. Each stage shows textual state, icon, timestamp when available, authority/source, and expandable provenance. Completed means that stage recorded an outcome, not that the case succeeded.

The UI contains no arbitrary connector target, URL, free-form command, or direct merchant-action control. T122-T124 display action state and submit only approved typed UI commands through backend APIs.

## 15. UNKNOWN / Reconciliation UX

UNKNOWN is a first-class execution state:

> UNKNOWN — remote result unresolved. Reconciliation is required before retry.

It uses a segmented neutral/steel icon plus explicit wording, never a checkmark or success color. Retry controls are absent while reconciliation is required. Show last remote attempt, reconciliation state, last reconciled time, remote reference when safe, and the next permitted operation. Unresolved reconciliation leads to escalation.

## 16. Verification UX

Verification is shown adjacent to execution and contains observed merchant-controlled state, verifier source, method/version, evidence references, checksum when available, timestamp, and one result:

- Verified success
- Verified failure
- Inconclusive

Inconclusive is never success. It immediately reveals escalation status and required human decision.

## 17. Escalation UX

The escalation panel shows owner, reason, remaining exposure and currency, evidence links, recommended human decision, linked action/execution/verification/policy identities, state, and timestamps.

Only an authorized tenant-scoped escalation owner sees resolution commands. Resolving escalation creates authoritative follow-up state; it does not rewrite terminal history or audit records. Missing ownership is a visible blocker, not an empty field.

## 18. Terminal Outcome UX

Only these terminal case outcomes are valid:

- `verified_contained`
- `verified_failed`
- `escalated_unresolved`

Each uses text, icon, and semantic treatment. A generic `closed`, `success`, or `resolved` case label is forbidden. Terminal case history is immutable; later follow-up is appended.

## 19. Audit / Provenance UX

Audit is a persistent bottom trace region. Narrative is the default view. Contextual links from events, policy, approval, action, reconciliation, verification, and escalation open the trace at the relevant record.

Narrative explains who or what acted, why, on which evidence, under which policy, and what followed. Technical Chain expands evidence/input/output references, correlations, model/provider versions, policy version, approval ID, canonical action identity, execution attempts, verification lineage, timestamps, and checksums.

Audit is visibly read-only and immutable. Copy/export may be read-only; edit, delete, reorder, or annotate-in-place affordances are forbidden.

## 20. LIVE / REPLAY UX

Mode appears at three deliberate levels only:

1. Global top-bar statement.
2. Permanent case-header badge.
3. Action/simulation notice in the decision region.

Avoid redundant labels elsewhere unless a specific artifact requires provenance.

REPLAY wording is `REPLAY — simulation / no merchant actions`. Replay controls begin with `Simulate`, `Run simulated`, or `Inspect recorded`; plain live-looking action labels are forbidden. Recorded outcomes are explicitly read-only.

LIVE wording states connector/provider qualification but remains separate from `live actions enabled`. Live financial execution is disabled by default. The UI must display requested mode, effective mode, final mode, fallback reason, provider/connector availability, `live_execution_occurred`, and live-action enablement from authoritative backend state; frontend environment variables are not truth.

## 21. Typography

Recommended implementation family is IBM Plex Sans Variable with IBM Plex Mono for technical identifiers, subject to package/licensing validation during T122. Use a readable system-sans fallback.

- Operational body/table text: 12-14px with readable line height.
- Panel titles: 14-16px.
- Case title: approximately 18px.
- Remaining Exposure: approximately 24-28px.
- Use tabular lining figures for money and timestamps.
- Monospace only for IDs, timestamps, hashes, checksums, versions, and provider references.
- Do not use oversized headings, fluid marketing type, or repeated uppercase eyebrow labels.

## 22. Color System

Canonical planning values use OKLCH and must be contrast-tested in the rendered implementation:

```css
--color-bg: oklch(0.145 0.008 230);
--color-surface-1: oklch(0.185 0.010 225);
--color-surface-2: oklch(0.220 0.012 225);
--color-border: oklch(0.330 0.012 225);
--color-ink: oklch(0.930 0.006 220);
--color-muted: oklch(0.720 0.010 220);
--color-reclaim: oklch(0.720 0.105 195);
--color-reclaim-strong: oklch(0.790 0.120 195);
```

Deep graphite is not pure black. Mineral teal is the sole RECLAIM brand accent and should occupy no more than roughly ten percent of a normal screen. Surface differences and thin borders create hierarchy; no glow is permitted.

## 23. Semantic State Colors

Provisional semantic anchors:

```css
--color-malicious: oklch(0.680 0.180 25);
--color-approval-required: oklch(0.780 0.150 80);
--color-uncertain: oklch(0.800 0.135 90);
--color-verified: oklch(0.720 0.140 150);
--color-informational: oklch(0.740 0.100 240);
--color-unknown: oklch(0.710 0.055 245);
```

Approval required and uncertain may share an amber family only when their icon, label, and structure remain unambiguous. UNKNOWN uses a neutral steel treatment. Filled semantic controls use text selected for both WCAG and perceptual contrast. Semantic colors remain local and never flood whole panels.

## 24. Spacing and Density

- Base unit: 4px.
- Common gaps: 8px, 12px, 16px.
- Panel padding: 12px desktop, 10px constrained.
- Compact controls: 32-36px height.
- Default table row: 44-56px before expansion.
- Workspace gutter: 12px desktop, 8px tablet/mobile.
- Body copy line length: 65-75ch when narrative; table content may run wider.
- Density presets are not user-configurable in T122-T124; ship one balanced-dense standard.

## 25. Component Styling

- **Panels:** 4-8px radius, thin full border, no broad shadow, no nested card decoration.
- **Buttons:** 4-6px radius; primary teal for safe non-destructive commands, consequential approval uses distinct semantic treatment and exact wording.
- **Inputs/filters:** 4-6px radius, surface-2 fill, structural border, strong focus ring.
- **State labels:** icon + text + restrained local color; pill shape only when the badge/tag affordance is real.
- **Navigation:** quiet default, surface-filled active state, icon and visible/tooltip label; never color alone.
- **Timeline rows:** aligned columns, subtle row separator, clear selected/expanded state.
- **Lifecycle:** ordered compact stage ledger, not a celebratory progress bar.
- **Audit drawer:** non-modal region with Narrative and Technical Chain views.
- **Overlays:** only final confirmation, menus, tooltips, or necessary popovers; small structural shadow, correct portal/stacking behavior.

## 26. Motion

Use 150-220ms ease-out transitions for panel expansion, selection, approval recording, action submission, reconciliation updates, verification completion, and escalation creation. Do not animate layout properties when transform/opacity or an immediate state swap is sufficient.

No page-load choreography, looping decorative animation, bounce, elastic motion, or glowing pulse. Reduced motion makes transitions immediate or uses a short crossfade. Important state changes remain understandable from text and structure alone.

## 27. Accessibility

- WCAG 2.2 AA minimum in the approved dark theme.
- Full keyboard navigation and strong `:focus-visible` treatment.
- Skip links to investigation, decision, and audit.
- Logical focus order: shell → case header → investigation → decision → trace.
- Timeline rows expand with Enter/Space and expose relationships programmatically.
- Accessible table names, headers, sorting/filter descriptions, and row expansion state.
- Screen-reader announcements for consequential state changes, without noisy repeated updates.
- Status never depends only on color or animation.
- Icon-only navigation includes accessible names and visible labels on expansion/focus.
- Dialog focus trap and restoration only for true modal confirmation.
- Target sizing remains usable on tablet even under dense presentation.

## 28. Responsive Strategy

- **Desktop ≥1180px:** full split workspace with sticky decision rail and expandable bottom trace.
- **Tablet landscape:** split layout with narrower decision rail; approval remains supported.
- **Tablet portrait:** persistent Investigation and Decision workspace tabs; exact-action context is preserved across tab switches.
- **Mobile <768px:** read-only status and decision summary: mode, case state, Remaining Exposure, next decision, condensed timeline, and audit links. Full investigation parity and consequential approval/action commands are intentionally omitted.

Columns collapse by priority; hidden data moves into accessible row detail. Do not rely solely on horizontal scrolling.

## 29. Loading / Empty / Error States

- Use panel-shaped skeletons; no central spinner over an empty workspace.
- Empty timeline distinguishes collection pending, source unavailable, and genuinely no events.
- No proposal distinguishes no validated proposal from analysis not run.
- Approval distinguishes not required, required/absent, pending, and stale/invalid.
- Partial evidence preserves available facts and limitations.
- Permission denied reveals no cross-tenant data and states the required role.
- `409` stale command freezes the affected control, reloads authoritative state, and explains what changed.
- API/schema failure marks any retained content stale with timestamp and removes consequential commands.
- Provider fallback shows requested/effective/final mode and reason.
- Failed simulation never appears as a live failure or production outcome.

## 30. Component Map

| File | Purpose and information | State variants and interactions | Priority, responsive, accessibility |
|---|---|---|---|
| `frontend/src/app/cases/[caseId]/page.tsx` | Authenticated shell, case header, composite case read model, split workspace | Loading, missing, denied, stale, error, live/replay; coordinates refresh | Highest; desktop split, tablet tabs, mobile summary; landmarks and skip links |
| `CaseTimeline.tsx` | Chronology, event/resource, attribution, confidence, evidence, financial impact, provenance | Filter, sort where authoritative, expand row, open trace, relationship drill-down | Primary; responsive column priority; semantic table and keyboard expansion |
| `ExposureSummary.tsx` | Currency-separated Remaining, Recoverable, Contained, Gross, Irreversible values | Loading, no exposure, multiple currencies, stale calculation | Primary decision value; tabular figures; descriptive accessible totals |
| `ActionDecisionPanel.tsx` | Proposal, policy, exact-action identity, lifecycle, verification, next decision | No proposal, denied, approval required, unknown, verifying, terminal | Persistent rail; becomes tablet tab/mobile summary; ordered headings |
| `ApprovalPanel.tsx` | Exact packet, proposer/approver separation, policy/resource freshness | Required, approved, rejected, expired, revoked, stale, forbidden, submitting | Consequential; tablet supported, mobile read-only; exact confirmation and live regions |
| `EscalationPanel.tsx` | Owner, reason, remaining exposure, evidence, recommendation, linked authority | Open, missing owner, resolving, resolved follow-up, permission denied | High when unresolved; accessible owner/action descriptions |
| `ReplayPanel.tsx` | Fixture/provenance, requested/effective mode, simulation controls, recorded outcomes/differences | Replay available, fallback, running, complete, failed, unavailable | Contextual; controls always say simulated; progress announcements bounded |
| `ModeBadge.tsx` | Permanent LIVE/REPLAY identity and accessible explanation | Live, replay, fallback, unavailable, live-actions-disabled | Global and case header; text/icon/outline, never color-only |
| `AuditTrace.tsx` | Narrative-first immutable chain with technical expansion | Collapsed, anchored record, loading, empty, chain error | Persistent bottom region; non-modal; tab/region semantics and keyboard navigation |
| `frontend/src/lib/api.ts` | Runtime-validated tenant-scoped read models and typed commands | Success and typed 401/403/404/409/availability/schema errors | No visual role; never stores secrets or infers authority |

## 31. API / Interaction Map

T123 requires a read-only composite `OperatorCaseView` assembled from authoritative case, timeline, attribution, exposure, analysis/proposal, policy, approval, execution, verification, escalation, audit, and mode sources. A recommended route is `GET /tenants/{tenant_id}/cases/{case_id}/operator-view`; it introduces no new business state.

Existing/planned typed interactions:

| Interaction | Boundary | UI rule |
|---|---|---|
| Incident intake | `POST /tenants/{tenant_id}/incidents` | Authenticated reviewer; show accepted/duplicate/rejected/quarantined exactly |
| Approval request/decision | `/tenants/{tenant_id}/approvals/*` | Exact proposal binding, optimistic version, role/separation enforcement |
| Workflow acknowledgement | `/tenants/{tenant_id}/cases/{case_id}/workflow/signals` where required | Never merge multi-call results into fabricated success; read back authority |
| Action status | `GET /tenants/{tenant_id}/actions/{execution_id}` | Read-only lifecycle; no connector invocation from UI |
| Escalation | `/tenants/{tenant_id}/escalations*` | Owner-scoped commands, version conflict handling |
| Replay | `POST /tenants/{tenant_id}/cases/{case_id}/replay` | Simulation-only language and result labeling |
| Audit | `GET /tenants/{tenant_id}/audit?case_id=...` | Read-only narrative/technical transformation |
| Mode availability | T124 `backend/api/demo.py` endpoint | Requested/effective/final mode, availability, fallback, action enablement |

`api.ts` must validate all responses with Zod, preserve integer minor units, bind tenant/case to authenticated context, distinguish error classes, and refetch authoritative state after commands. It must never accept arbitrary URLs, SQL, credentials, connector methods, or free-form executable instructions.

## 32. T122 Implementation Guidance

Implement the case page and three core components as one vertical UI slice: shell/header, timeline, exposure, and decision rail. Begin with typed fixtures only in tests; production rendering must consume the authoritative read model. Preserve the 66/34 desktop hierarchy and bottom trace slot. Implement loading/error/permission/empty states alongside the default state, not afterward.

Do not add charts merely because the visual reference contains charts. Validate the page against the canonical mixed malicious/legitimate/uncertain fixture and explicit terminal variants.

## 33. T123 Implementation Guidance

Implement `api.ts` contracts before interactive panels. Approval, escalation, replay, audit, and evaluation provenance must be tenant-scoped, runtime-validated, and role-aware. UI commands submit typed intent only; backend validation, policy, approval authority, Action Gateway, verification, and audit remain unchanged.

Approval and escalation use optimistic version handling. Audit remains read-only. If approval recording and workflow signalling are separate calls, present their states separately until the composite read model confirms progression. No client-side state may stand in for PostgreSQL authority.

## 34. T124 Implementation Guidance

Implement backend mode selection/availability before wiring visual mode state. The mode endpoint must expose requested, effective, and final mode; availability reasons; fallback reason; provider/connector qualification; whether live execution occurred; and whether live actions are enabled.

`ModeBadge` consumes this authoritative value. REPLAY changes action-region structure, not merely color. LIVE never implies live financial execution. Provider failure selects labeled replay or escalation according to backend policy; the UI never fabricates LIVE from configuration.

## 35. Anti-Patterns / Explicit Bans

- Generic SOC, cybersecurity, fintech admin, executive KPI, trading, gambling, crypto, or AI SaaS dashboard styling.
- Executive charts, security gauges, fake trends, fake metrics, or equal KPI-card grids.
- Cream/beige SaaS, fintech navy/gold, purple AI gradients, neon hacker green, blue glow, glassmorphism, or cyberpunk treatment.
- Nested cards, giant decorative metrics, 24-32px panel radii, broad ghost-card shadows, badge spam, decorative grid/stripe backgrounds, gradient text, or colored side-stripe borders.
- Graph-first navigation, modal-first approval, manipulative confirmation, or plain live-looking controls in REPLAY.
- Tiny text, compressed line height, monospace everywhere, status by color alone, or motion-gated comprehension.
- Generic `closed`/`success` terminal states, UNKNOWN shown as success, inconclusive verification shown as success, or uncertain attribution shown as weak maliciousness.
- Editable audit history, direct record mutation, client-derived financial truth, or client-inferred LIVE availability.

## 36. Security / Authority UX Constraints

- The model remains advisory; model confidence is labeled and cannot authorize an action.
- Deterministic policy result and immutable version are visibly separate from the proposal.
- Required approval cannot be bypassed; proposer and approver separation is visible and enforced by backend authority.
- The UI never invokes merchant connectors, the Action Gateway, a database, shell, or arbitrary network target directly.
- Every side effect remains typed proposal → deterministic validation/policy → required approval → isolated idempotent Action Gateway → reconciliation → verification → audit.
- Financial values are authoritative backend values; refunds reference captured payment and original source only.
- UNKNOWN blocks retry until reconciliation. Inconclusive verification routes to escalation.
- Only approved terminal states appear. Audit is append-only and tenant/case scope is authoritative.
- Untrusted evidence/model text is rendered safely and cannot become instructions, markup, URLs, permissions, or executable commands.
- Live financial execution remains disabled by default and receives a separate visible indicator.

## 37. Impeccable Guidance for Build Phase

- Re-run `$impeccable document` after the first implemented tokens/components so `DESIGN.md` becomes a scan-derived system rather than a seed.
- Use the approved reference only for shell proportions, density, panel framing, spacing rhythm, and enterprise organization.
- Apply the product register: familiar operational affordances, one coherent component vocabulary, restrained state motion, skeleton loading, and structural responsive behavior.
- Reject all Impeccable absolute bans, especially side-stripe accents, gradient text, glassmorphism, oversized rounding, broad border-plus-shadow cards, decorative grids/stripes, and repeated tiny uppercase eyebrows.
- Validate contrast, focus, overflow, keyboard order, reduced motion, tablet behavior, and REPLAY structure in a real browser before declaring T122-T124 complete.
- Generated mockups are direction probes only; code, contracts, accessibility semantics, and authoritative data win over pixels.

## 38. Acceptance Checklist

### Shell and hierarchy

- [ ] Compact navigation, top bar, persistent case header, investigation region, decision rail, and audit region are present.
- [ ] Investigation timeline/table is the primary visual spine.
- [ ] Remaining Exposure is the dominant financial value; other amounts form an ordered ledger.
- [ ] Exact-action packet and next-human-decision area remain persistent on desktop/tablet approval layouts.
- [ ] Balanced-dense text remains readable and is not artificially tiny.

### Semantics and safety

- [ ] Malicious, legitimate, and uncertain use icon + label + structure + color.
- [ ] Uncertain does not resemble weak maliciousness.
- [ ] Approval required is distinct from informational blue.
- [ ] Proposal, policy, approval, execution, reconciliation, verification, and terminal authority are separately visible.
- [ ] UNKNOWN explicitly requires reconciliation and cannot appear successful.
- [ ] Inconclusive verification cannot appear successful and exposes escalation.
- [ ] Only `verified_contained`, `verified_failed`, and `escalated_unresolved` appear as terminal states.
- [ ] Audit is narrative-first, technically expandable, and visibly immutable.
- [ ] No direct record, connector, database, or arbitrary network mutation exists in frontend code.

### LIVE / REPLAY

- [ ] Mode appears in global header, case header, and action/simulation notice without redundant spam.
- [ ] Mode is understandable without color.
- [ ] REPLAY contains only explicit simulation or recorded-outcome controls.
- [ ] LIVE, availability, execution occurrence, and live-action enablement are separate facts from backend authority.
- [ ] Provider unavailability produces truthful fallback or escalation, never fabricated LIVE.

### Quality and accessibility

- [ ] WCAG 2.2 AA contrast is measured for body, muted, semantic, focus, and control states.
- [ ] Full keyboard flow, skip links, focus visibility/restoration, table semantics, and screen-reader labels pass.
- [ ] Reduced-motion behavior preserves comprehension.
- [ ] Desktop, tablet landscape/portrait, and mobile summary behavior are verified.
- [ ] Loading, empty, partial, denied, stale, schema-error, and command-conflict states are implemented.
- [ ] No glassmorphism, gradients, glow, over-carding, giant rounding, fake charts/metrics, cyberpunk styling, or generic AI dashboard patterns remain.
- [ ] Browser acceptance test `tests/browser/test_operator_workflow.py` passes without record-mutation terms or missing review fields.
- [ ] Production code, tests, and status are not marked complete until their actual validation gates pass.
