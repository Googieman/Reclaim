# Case Inbox UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the RECLAIM operator frontend route-backed, responsive, keyboard-accessible, and interaction-complete while displaying only authoritative API data.

**Architecture:** Keep the existing typed tenant-scoped API and Next.js App Router. Extract shared navigation and route-surface primitives, keep inbox filtering server-backed and sorting/selection view-local, and preserve the existing case-detail workflow and safety boundaries. Add read-only route surfaces for services, reviews, runs, and audit; where no authoritative collection API exists, state that explicitly instead of fabricating records.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Vitest, Playwright, CSS media queries, Zod-validated API models.

**Spec:** `specs/001-incident-intake-containment/spec.md` and the approved UI redesign requirements in the task request.

## Global Constraints

- PostgreSQL remains authoritative for business state; the frontend only consumes typed API read models and submits existing typed commands.
- n8n remains the durable orchestrator for new work; the UI must not execute actions, mutate records directly, or add arbitrary network calls.
- Financial values remain integer minor units and reported values remain visibly unverified.
- Do not invent incidents, services, runs, reviews, or audit records when an authoritative API collection is unavailable.
- Preserve unrelated dirty-worktree changes and keep Docker's `RECLAIM_API_INTERNAL_BASE_URL=http://api:8000` override behavior intact.
- Meet keyboard access, visible focus, reduced-motion, and mobile/tablet layout requirements.

---

### Task 1: Add red interaction and proxy tests

**Files:**
- Create: `frontend/src/components/cases/caseInboxModel.test.ts`
- Create: `frontend/src/components/cases/CaseInbox.browser.spec.ts`
- Create: `frontend/next.config.test.ts`
- Create: `frontend/playwright.config.ts`

**Interfaces:**
- Tests define the expected `caseInboxModel` helpers for navigation matching, deterministic client sorting, and selection toggling.
- Browser tests use a complete typed case-inbox fixture through Playwright request interception and assert user-visible navigation, filter requests, sort order, selection drawer, case links, keyboard dismissal, and responsive cards.

- [ ] **Step 1: Write failing unit tests** for route matching, stable sort direction, and selection toggling using literal fixtures.
- [ ] **Step 2: Write failing browser tests** for `/cases` navigation links, active state, query/state filter requests, sorting, row selection, detail links, intake drawer Escape handling, mobile navigation drawer, and stacked case cards.
- [ ] **Step 3: Write failing proxy tests** asserting the local default targets `http://127.0.0.1:8000` and an explicit `RECLAIM_API_INTERNAL_BASE_URL=http://api:8000` remains honored.
- [ ] **Step 4: Run the targeted tests** and confirm they fail because the new helpers/routes/behaviors do not yet exist.

### Task 2: Implement shared route-backed navigation and route surfaces

**Files:**
- Create: `frontend/src/components/navigation/AppNavigation.tsx`
- Create: `frontend/src/components/navigation/RouteSurface.tsx`
- Create: `frontend/src/app/services/page.tsx`
- Create: `frontend/src/app/reviews/page.tsx`
- Create: `frontend/src/app/runs/page.tsx`
- Create: `frontend/src/app/audit/page.tsx`
- Modify: `frontend/src/components/cases/CaseInbox.tsx`
- Modify: `frontend/src/app/cases/[caseId]/page.tsx`

**Interfaces:**
- `AppNavigation({ tenantId, counts? })` renders links for `/cases`, `/services`, `/reviews`, `/runs`, and `/audit`, marks exact/descendant routes with `aria-current`, and owns desktop/tablet/mobile navigation state.
- `RouteSurface({ tenantId, title, description, sourceNote })` renders an honest read-only empty/availability state for routes without an authoritative collection endpoint.

- [ ] **Step 1: Replace hard-coded inbox/detail sidebars with `AppNavigation`.**
- [ ] **Step 2: Add route-backed pages using `RouteSurface` without fabricated records.**
- [ ] **Step 3: Add mobile hamburger, focus return, Escape close, and body-scroll lock behavior to the navigation drawer.
- [ ] **Step 4: Run unit and browser navigation tests.**

### Task 3: Implement inbox sorting, selection, drawers, and responsive cards

**Files:**
- Create: `frontend/src/components/cases/caseInboxModel.ts`
- Modify: `frontend/src/components/cases/CaseInbox.tsx`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- `sortCaseInboxItems(items, key, direction)` returns a new array sorted by `updated_at`, `occurred_at`, `state`, or `incident_type`, with case ID tie-breaking.
- `toggleCaseSelection(selectedIds, caseId)` returns a new selected-ID set.
- `isNavItemActive(pathname, href)` returns true for an exact route or a descendant case route.

- [ ] **Step 1: Implement the minimum helpers to make Task 1 unit tests pass.**
- [ ] **Step 2: Add sortable table headers with `aria-sort`, selection checkboxes, select-all state, and a selection summary drawer linking every selected case to its detail route.**
- [ ] **Step 3: Render the same API items as stacked mobile incident cards while keeping case detail links and selection available.**
- [ ] **Step 4: Make the intake and selection drawers modal, focusable, Escape-dismissable, and safe under reduced motion.**
- [ ] **Step 5: Add desktop full rail, tablet compact rail, and mobile hamburger/card CSS with explicit focus and state styles.**
- [ ] **Step 6: Run unit and browser tests and fix any behavior failures.

### Task 4: Fix local proxy default and verify the full surface

**Files:**
- Modify: `frontend/next.config.mjs`
- Modify: `frontend/next.config.test.ts` if test isolation requires an import-safe helper.

- [ ] **Step 1: Change only the fallback proxy target to `http://127.0.0.1:8000`.**
- [ ] **Step 2: Run targeted proxy tests and confirm explicit Docker environment overrides still produce `http://api:8000`.**
- [ ] **Step 3: Run `npm test -- --run`, `npm run typecheck`, `npm run lint`, and `npm run build`.**
- [ ] **Step 4: Start or reuse the local frontend, verify `http://localhost:3000/cases` in the running browser at desktop, tablet, and mobile viewport sizes, and capture any remaining console/runtime errors.**
- [ ] **Step 5: Review the diff and status to ensure unrelated dirty files were not modified.

## Self-review checklist

- All five sidebar destinations are real Next routes and all active states are URL-derived.
- API filter controls pass only supported tenant-scoped query parameters; local sorting never invents or edits data.
- Selected rows/cards provide case-detail links and no mutation controls.
- Mobile layout uses the hamburger drawer and stacked cards; tablet uses a compact rail.
- Drawer focus, Escape behavior, visible focus, and reduced-motion behavior are tested or directly verified.
- Proxy tests cover both local default and Docker override.
- No completion claim is made without fresh test, typecheck, lint, build, and browser evidence.
