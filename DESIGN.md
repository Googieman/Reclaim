<!-- SEED: re-run $impeccable document once T122-T124 UI code exists to capture the implemented tokens and components. -->
---
name: RECLAIM Operator UI
description: A dark, balanced-dense incident command workspace for verified fraud-loss containment.
---

# Design System: RECLAIM Operator UI

## Overview

**Creative North Star: "The Incident Command Ledger"**

RECLAIM combines the compact discipline of an enterprise risk console with the traceability of an engineering ledger. The case is the workspace: investigative chronology occupies the primary field, deterministic decision authority remains persistently visible, and immutable provenance is always within reach. The interface is dark, calm, exact, and information-rich without becoming visually exhausting.

The approved reference contributes shell proportions, narrow navigation, restrained rectangular panels, compact headers, thin separation, and predictable data alignment. It does not contribute executive-dashboard charts, equal KPI tiles, branding, or generic SOC imagery. The visual system must feel designed specifically for merchant fraud-loss containment.

**Key Characteristics:**

- Dark graphite application shell with restrained mineral-teal RECLAIM accent.
- Compact left navigation, top bar, persistent case header, split investigation/decision workspace, and bottom trace region.
- Balanced-dense typography and spacing suitable for long operator sessions.
- Rectangular operational panels with minimal radius and tonal separation.
- State communication through text, icon, structure, and color together.
- Restrained motion used only to explain operational state changes.

## Colors

The palette is restrained: deep neutral graphite carries the workspace, mineral teal identifies RECLAIM and interactive focus, and semantic colors appear only where they communicate authoritative state. Exact production values are defined in the approved UI handoff and must be contrast-qualified during T122-T124 implementation.

### Primary

- **Mineral Signal Teal** `[resolve from approved handoff during implementation]`: RECLAIM identity, focus, current navigation, selected filters, and primary non-destructive interaction. It is not decorative and must remain visually scarce.

### Neutral

- **Command Graphite** `[resolve during implementation]`: deep neutral application background; never pure black.
- **Instrument Surface** `[resolve during implementation]`: primary workspace and panel surface.
- **Raised Instrument Surface** `[resolve during implementation]`: headers, selected rows, and secondary containment regions.
- **Structural Divider** `[resolve during implementation]`: thin panel, row, and column separation.
- **Operational Ink** `[resolve during implementation]`: primary text with strong dark-theme contrast.
- **Muted Telemetry** `[resolve during implementation]`: secondary text that still meets WCAG 2.2 AA where required.

### Named Rules

**The One Signal Rule.** Mineral teal is the sole brand accent and occupies no more than roughly ten percent of a normal workspace.

**The Semantic Containment Rule.** Malicious, uncertain, legitimate/verified, informational, approval-required, and replay states each receive bounded semantic treatment; no semantic color floods an entire panel.

**The Mode Is Structural Rule.** LIVE and REPLAY use words, icons, placement, and outline treatment in addition to color.

## Typography

**Display Font:** Single technical-authoritative sans `[font family to be chosen during implementation]`
**Body Font:** Same highly readable product sans
**Label/Mono Font:** Purpose-built monospace `[font family to be chosen during implementation]`

**Character:** Compact, neutral, and authoritative. The sans family carries the interface; monospace is restricted to machine-readable identifiers and provenance.

### Hierarchy

- **Headline:** Compact case and major-region titles; never marketing scale.
- **Title:** Panel headers and consequential decision headings.
- **Body:** Primary operational reading, generally 12-14px at desktop with comfortable line height.
- **Label:** Dense table headings, field names, navigation labels, and state descriptors.
- **Mono:** Event IDs, case IDs, timestamps, hashes, checksums, versions, provider references, and canonical action identities only.

### Named Rules

**The Human Reading Rule.** Explanations, rationales, decisions, and next actions always use the primary sans; machine typography must never dominate the workspace.

**The Honest Density Rule.** Density comes from alignment and hierarchy, never artificially tiny text or compressed line height.

## Elevation

RECLAIM is flat by default. Depth comes from deliberate surface-tone changes, thin borders, and spatial grouping. Shadows are reserved for true overlays such as a final confirmation dialog or detached popover, and remain small and structural.

**The Flat Instrument Rule.** If a panel requires a large soft shadow to appear separate, its surface hierarchy or border structure is wrong.

## Do's and Don'ts

### Do:

- **Do** preserve the compact left navigation, top bar, case header, investigation workspace, decision rail, and immutable trace region.
- **Do** make the investigation table/timeline hybrid the primary visual spine.
- **Do** make Remaining Exposure the dominant financial value and preserve integer-minor-unit authority.
- **Do** keep the exact-action packet and next-human-decision region persistent.
- **Do** make approval-required status distinct from ordinary informational blue.
- **Do** communicate malicious, legitimate, uncertain, UNKNOWN, verification, terminal, and mode states with icon, text, structure, and color.
- **Do** design desktop first, meaningful tablet review/approval second, and mobile status/summary third.
- **Do** meet WCAG 2.2 AA, complete keyboard navigation, strong focus visibility, reduced motion, and screen-reader semantics.

### Don't:

- **Don't** produce a generic SOC dashboard, cybersecurity console, fintech admin panel, executive KPI dashboard, trading platform, gambling interface, crypto interface, or generic AI SaaS dashboard.
- **Don't** use cream/beige SaaS palettes, purple AI gradients, glassmorphism, neon hacker green, generic dark-security blue glow, fintech navy, or navy-plus-gold.
- **Don't** use disconnected or nested card collections, giant decorative metrics, fake charts, graph-first navigation, badge spam, giant empty areas, or visual density without operational value.
- **Don't** use manipulative confirmations, modal-first approvals, plain live-looking action controls in REPLAY, or styling that makes uncertain evidence look like weakly malicious evidence.
- **Don't** use colored side-stripe borders, gradient text, decorative grid backgrounds, repeating stripes, 24-32px panel radii, broad ghost-card shadows, or decorative looping motion.
