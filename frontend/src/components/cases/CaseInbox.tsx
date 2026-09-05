"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  listCases,
  getModeAvailability,
  ReclaimApiError,
  submitIncidentIntake,
  type CaseInboxFilters,
  type ModeAvailability,
  type CaseInboxItem,
} from "@/lib/api";
import { AppNavigation } from "@/components/navigation/AppNavigation";
import { sortCaseInboxItems, toggleCaseSelection, type CaseSortKey, type SortDirection } from "./caseInboxModel";

const PAGE_SIZE = 25;
const POLLABLE_STATUSES = new Set(["queued", "running"]);
const CURRENCY_MINOR_UNITS: Record<string, number> = {
  BHD: 3,
  CLP: 0,
  CNY: 2,
  EUR: 2,
  GBP: 2,
  INR: 2,
  JPY: 0,
  KWD: 3,
  KRW: 0,
  RUB: 2,
  SGD: 2,
  USD: 2,
  VND: 0,
};

const STATE_OPTIONS = [
  ["", "All case states"],
  ["intake_received", "Intake received"],
  ["collecting_evidence", "Collecting evidence"],
  ["timeline_ready", "Timeline ready"],
  ["analyzed", "Analyzed"],
  ["action_pending", "Action pending"],
  ["containing", "Containing"],
  ["verified_contained", "Verified contained"],
  ["verified_failed", "Verified failed"],
  ["escalated_unresolved", "Escalated unresolved"],
] as const;

const AUTOMATION_OPTIONS = [
  ["", "All automation"],
  ["queued", "Queued"],
  ["running", "Running"],
  ["awaiting_human", "Awaiting human"],
  ["completed", "Completed"],
  ["failed", "Failed"],
  ["requires_attention", "Requires attention"],
] as const;

export function CaseInbox({ tenantId }: { tenantId: string }) {
  const [items, setItems] = useState<CaseInboxItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [hasMore, setHasMore] = useState(false);
  const [state, setState] = useState("");
  const [automationStatus, setAutomationStatus] = useState("");
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectionDrawerOpen, setSelectionDrawerOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<CaseSortKey | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("descending");
  const [highlightedCaseId, setHighlightedCaseId] = useState<string | null>(null);
  const [notice, setNotice] = useState("Loading authoritative cases.");
  const [error, setError] = useState<ReclaimApiError | null>(null);
  const [mode, setMode] = useState<ModeAvailability | null>(null);
  const commandSearchRef = useRef<HTMLInputElement>(null);
  const requestSequence = useRef(0);

  const load = useCallback(
    async (
      cursor?: string,
      background = false,
      filterOverrides: Partial<CaseInboxFilters> = {},
    ) => {
      const requestId = ++requestSequence.current;
      if (background) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const page = await listCases(tenantId, {
          state: filterOverrides.state ?? (state || undefined),
          automationStatus: filterOverrides.automationStatus ?? (automationStatus || undefined),
          query: filterOverrides.query ?? (activeQuery || undefined),
          limit: PAGE_SIZE,
          cursor,
        });
        if (requestId !== requestSequence.current) return;
        setItems((current) => cursor ? [...current, ...page.items] : page.items);
        setNextCursor(page.next_cursor ?? undefined);
        setHasMore(page.has_more);
        setNotice(
          page.items.length === 0
            ? "No cases match the current filters."
          : `${page.items.length} authoritative case${page.items.length === 1 ? "" : "s"} loaded.`,
        );
      } catch (reason) {
        if (requestId !== requestSequence.current) return;
        const nextError = reason instanceof ReclaimApiError
          ? reason
          : new ReclaimApiError("The authoritative case inbox could not be loaded.", "network");
        setError(nextError);
        setNotice("Case inbox unavailable. Consequential controls remain withheld.");
      } finally {
        if (requestId === requestSequence.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [activeQuery, automationStatus, state, tenantId],
  );

  useEffect(() => {
    let active = true;
    void getModeAvailability(tenantId)
      .then((nextMode) => {
        if (active) setMode(nextMode);
      })
      .catch(() => {
        if (active) setMode(null);
      });
    return () => {
      active = false;
    };
  }, [tenantId]);

  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        commandSearchRef.current?.focus();
      }
      if (event.key === "Escape") {
        setDrawerOpen(false);
        setSelectionDrawerOpen(false);
      }
    };
    document.addEventListener("keydown", handleShortcut);
    return () => document.removeEventListener("keydown", handleShortcut);
  }, []);

  const hasPollableRun = useMemo(
    () => items.some((item) => item.orchestration && POLLABLE_STATUSES.has(item.orchestration.status)),
    [items],
  );

  const queueSummary = useMemo(() => ({
    queued: items.filter((item) => item.orchestration?.status === "queued").length,
    running: items.filter((item) => item.orchestration?.status === "running").length,
    awaiting: items.filter((item) => item.orchestration?.status === "awaiting_human").length,
    attention: items.filter((item) => item.orchestration?.status === "requires_attention").length,
  }), [items]);

  const visibleItems = useMemo(
    () => sortKey ? sortCaseInboxItems(items, sortKey, sortDirection) : items,
    [items, sortDirection, sortKey],
  );

  const selectedItems = useMemo(
    () => visibleItems.filter((item) => selectedIds.has(item.case_id)),
    [selectedIds, visibleItems],
  );

  const allVisibleSelected = visibleItems.length > 0 && visibleItems.every((item) => selectedIds.has(item.case_id));

  useEffect(() => {
    if (!hasPollableRun) return undefined;
    const timer = window.setInterval(() => void load(undefined, true), 8000);
    return () => window.clearInterval(timer);
  }, [hasPollableRun, load]);

  function applySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSelectedIds(new Set());
    setActiveQuery(query.trim());
  }

  function resetFilters() {
    setSelectedIds(new Set());
    setState("");
    setAutomationStatus("");
    setQuery("");
    setActiveQuery("");
  }

  function selectQueue(status: string) {
    setSelectedIds(new Set());
    setState("");
    setAutomationStatus(status);
    setQuery("");
    setActiveQuery("");
  }

  function changeSort(nextKey: CaseSortKey) {
    if (sortKey === nextKey) {
      setSortDirection((current) => current === "ascending" ? "descending" : "ascending");
      return;
    }
    setSortKey(nextKey);
    setSortDirection("descending");
  }

  function toggleSelectAll() {
    setSelectedIds((current) => {
      if (allVisibleSelected) return new Set([...current].filter((caseId) => !visibleItems.some((item) => item.case_id === caseId)));
      return new Set([...current, ...visibleItems.map((item) => item.case_id)]);
    });
  }

  function toggleSelectedCase(caseId: string) {
    setSelectedIds((current) => toggleCaseSelection(current, caseId));
  }

  function handleIntakeAccepted(caseId: string | null) {
    setDrawerOpen(false);
    setState("");
    setAutomationStatus("");
    setQuery("");
    setActiveQuery("");
    setHighlightedCaseId(caseId);
    const intakeNotice = caseId ? `Incident accepted. Case ${caseId} is highlighted.` : "Incident accepted; refreshing authoritative cases.";
    setNotice(intakeNotice);
    void load(undefined, false, { state: undefined, automationStatus: undefined, query: undefined }).then(() => setNotice(intakeNotice));
  }

  const modeLabel = mode ? humanize(mode.label).toUpperCase() : "MODE PENDING";
  const modeClass = mode ? `mode-badge--${mode.final_mode}` : "";
  const modeMark = mode?.final_mode === "replay" ? "◇" : mode?.final_mode === "escalation" ? "!" : "●";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#case-list">Skip to case list</a>
      <a className="skip-link" href="#intake-panel">Skip to intake form</a>
      <AppNavigation tenantId={tenantId} counts={{ cases: items.length, attention: queueSummary.attention }} />

      <div className="main-column cases-main">
        <header className="top-bar">
          <div className="top-bar__identity"><span className="mobile-brand-mark" aria-hidden="true">R</span><span>Incident command</span></div>
          <form className="top-command-search" onSubmit={applySearch} role="search"><span aria-hidden="true">⌕</span><input ref={commandSearchRef} aria-label="Search incidents" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search incidents" maxLength={100} /><kbd>⌘ K</kbd></form>
          <div className="top-bar__context"><span className="context-label">Tenant</span><strong>{tenantId}</strong><span className="context-divider" aria-hidden="true" /><span className={`mode-badge ${modeClass}`} aria-label={mode ? `${modeLabel}: ${mode.simulation_notice}` : "Mode pending"} title={mode?.simulation_notice}><span className="mode-badge__mark" aria-hidden="true">{modeMark}</span>{modeLabel}</span></div>
          <div className="top-bar__actions"><button type="button" className="top-bar-icon" aria-label="Open notifications">◌</button><button type="button" className="top-bar-icon" aria-label="Open help">?</button><span className="operator-identity"><span className="operator-avatar operator-avatar--small">RO</span><span>Reviewer</span></span></div>
        </header>

        <section className="inbox-header" aria-labelledby="inbox-title">
          <div>
            <p className="section-kicker">Incident response</p>
            <h1 id="inbox-title">Incidents</h1>
            <p className="case-context">Triage merchant incidents, follow orchestration progress, and hand off decisions safely.</p>
          </div>
          <div className="inbox-header__actions"><span className="inbox-header__scope">{tenantId}</span><button type="button" className="button button--primary" onClick={() => setDrawerOpen(true)} aria-expanded={drawerOpen} aria-controls="intake-panel"><span aria-hidden="true">＋</span> New incident</button></div>
        </section>

        <div className="workspace-notice" role="status" aria-live="polite">
          <span aria-hidden="true">◌</span>
          <span>{notice}</span>
          {hasPollableRun ? <span className="workspace-notice__evaluation">Auto-refreshing queued and running work</span> : null}
        </div>

        <main className="inbox-layout">
          <section className="panel case-list-panel" id="case-list" aria-labelledby="case-list-title">
            <div className="panel-heading panel-heading--with-controls">
              <div><h2 id="case-list-title">Incident queue</h2><p className="panel-subtitle">Authoritative cases · newest updates first</p></div>
              <button type="button" className="button button--quiet" onClick={() => void load(undefined, true)} disabled={loading || refreshing}>{refreshing ? "Refreshing…" : "Refresh"}</button>
            </div>

            <div className="queue-tabs" role="tablist" aria-label="Incident queue views">
              {[["", "All incidents"], ["queued", "Queued"], ["running", "In progress"], ["awaiting_human", "Awaiting review"], ["requires_attention", "Needs attention"]].map(([value, label]) => <button key={value || "all"} type="button" role="tab" aria-selected={automationStatus === value && !state && !activeQuery} className={automationStatus === value && !state && !activeQuery ? "queue-tab queue-tab--active" : "queue-tab"} onClick={() => selectQueue(value)}>{label}{value === "requires_attention" && queueSummary.attention > 0 ? <span className="queue-tab__count">{queueSummary.attention}</span> : null}</button>)}
            </div>

            <div className="inbox-summary" aria-label="Current page summary">
              <SummaryMetric label="On this page" value={items.length} detail="visible cases" />
              <SummaryMetric label="In progress" value={queueSummary.queued + queueSummary.running} detail={queueSummary.running ? `${queueSummary.running} running` : "no active runs"} />
              <SummaryMetric label="Awaiting review" value={queueSummary.awaiting} detail="human handoff" />
              <SummaryMetric label="Needs attention" value={queueSummary.attention} detail="failed or blocked" tone={queueSummary.attention ? "attention" : undefined} />
            </div>

            <form className="inbox-toolbar" onSubmit={applySearch} role="search">
              <label className="search-field"><span>Identifier search</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Case, order, account, payment…" maxLength={100} /></label>
              <label className="filter-control"><span>Case state</span><select value={state} onChange={(event) => { setSelectedIds(new Set()); setState(event.target.value); }}>{STATE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label className="filter-control"><span>Automation</span><select value={automationStatus} onChange={(event) => { setSelectedIds(new Set()); setAutomationStatus(event.target.value); }}>{AUTOMATION_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <button type="submit" className="button button--quiet">Search</button>
              <button type="button" className="text-button clear-filters" onClick={resetFilters}>Clear</button>
            </form>

            {selectedIds.size > 0 ? <div className="selection-toolbar" role="region" aria-label="Selected cases">
              <span><strong>{selectedIds.size}</strong> {selectedIds.size === 1 ? "case" : "cases"} selected</span>
              <div><button type="button" className="button button--quiet" onClick={() => setSelectionDrawerOpen(true)}>Review selected cases</button><button type="button" className="text-button" onClick={() => setSelectedIds(new Set())}>Clear selection</button></div>
            </div> : null}

            {loading ? <InboxSkeleton /> : error && items.length === 0 ? <InboxError error={error} onRetry={() => void load()} /> : items.length === 0 ? <EmptyInbox onCreate={() => setDrawerOpen(true)} /> : (
              <>
                <div className="case-table-wrap">
                  <table className="case-table">
                    <caption className="sr-only">Tenant-scoped incident queue</caption>
                    <thead><tr>
                      <th scope="col" className="case-table__select"><input type="checkbox" aria-label="Select all visible cases" checked={allVisibleSelected} onChange={toggleSelectAll} /></th>
                      <SortableHeader label="Incident" sortKey="incident_type" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
                      <th scope="col">Case</th>
                      <SortableHeader label="Occurred" sortKey="occurred_at" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
                      <SortableHeader label="State" sortKey="state" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
                      <th scope="col">Orchestration</th>
                      <SortableHeader label="Updated" sortKey="updated_at" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
                    </tr></thead>
                    <tbody>{visibleItems.map((item) => <CaseRow key={item.case_id} item={item} selected={selectedIds.has(item.case_id)} highlighted={item.case_id === highlightedCaseId} onToggle={() => toggleSelectedCase(item.case_id)} />)}</tbody>
                  </table>
                </div>
                <div className="case-card-list" aria-label="Incident cards">{visibleItems.map((item) => <CaseCard key={item.case_id} item={item} selected={selectedIds.has(item.case_id)} highlighted={item.case_id === highlightedCaseId} onToggle={() => toggleSelectedCase(item.case_id)} />)}</div>
              </>
            )}

            {!loading && items.length > 0 ? <div className="pagination-bar"><span>{hasMore ? "More cases available" : "End of current case list"}</span><button type="button" className="button button--quiet" disabled={!nextCursor || loading} onClick={() => void load(nextCursor)}>{nextCursor ? "Load more" : "No more cases"}</button></div> : null}
          </section>

          {drawerOpen ? <IncidentIntakePanel tenantId={tenantId} onClose={() => setDrawerOpen(false)} onAccepted={handleIntakeAccepted} /> : null}
          {selectionDrawerOpen ? <SelectedCasesDrawer items={selectedItems} onClose={() => setSelectionDrawerOpen(false)} /> : null}
        </main>
      </div>
    </div>
  );
}

function SortableHeader({ label, sortKey, activeKey, direction, onSort }: { label: string; sortKey: CaseSortKey; activeKey: CaseSortKey | null; direction: SortDirection; onSort: (key: CaseSortKey) => void }) {
  const active = activeKey === sortKey;
  return <th scope="col" aria-sort={active ? direction : "none"}><button type="button" className="table-sort-button" aria-label={`Sort by ${label}`} onClick={() => onSort(sortKey)}>{label}<span aria-hidden="true">{active ? direction === "ascending" ? " ↑" : " ↓" : " ↕"}</span></button></th>;
}

function CaseRow({ item, selected, highlighted, onToggle }: { item: CaseInboxItem; selected: boolean; highlighted: boolean; onToggle: () => void }) {
  const orchestration = item.orchestration;
  return (
    <tr className={highlighted ? "case-row case-row--highlighted" : "case-row"} data-case-row>
      <td className="case-table__select"><input type="checkbox" aria-label={`Select case ${item.case_id}`} checked={selected} onChange={onToggle} /></td>
      <td><strong className="case-incident-title">{humanize(item.incident_type)}</strong><span className="table-secondary">{item.source} · {item.merchant_name}</span></td>
      <td><Link className="case-link" href={`/cases/${encodeURIComponent(item.case_id)}`}>{item.case_id}</Link><span className="table-secondary">{item.external_reference ?? "No external reference"}</span></td>
      <td><time dateTime={item.occurred_at}>{formatDate(item.occurred_at)}</time><span className="table-secondary">{formatAmount(item.reported_amount_minor, item.reported_currency)}</span></td>
      <td><StatusLabel value={item.state} /></td>
      <td>{orchestration ? <><StatusLabel value={orchestration.status} /><span className="table-secondary">{humanize(orchestration.stage)}</span></> : <span className="table-secondary">Not started</span>}</td>
      <td><time dateTime={item.updated_at}>{formatDate(item.updated_at)}</time></td>
    </tr>
  );
}

function CaseCard({ item, selected, highlighted, onToggle }: { item: CaseInboxItem; selected: boolean; highlighted: boolean; onToggle: () => void }) {
  const orchestration = item.orchestration;
  return <article className={highlighted ? "case-card case-card--highlighted" : "case-card"} data-case-card>
    <div className="case-card__topline"><label className="case-card__select"><input type="checkbox" aria-label={`Select case ${item.case_id}`} checked={selected} onChange={onToggle} /><span>Select</span></label><StatusLabel value={item.state} /></div>
    <div className="case-card__title"><div><strong>{humanize(item.incident_type)}</strong><span>{item.source} · {item.merchant_name}</span></div><Link className="case-link" href={`/cases/${encodeURIComponent(item.case_id)}`}>{item.case_id}</Link></div>
    <dl className="case-card__facts"><div><dt>Occurred</dt><dd><time dateTime={item.occurred_at}>{formatDate(item.occurred_at)}</time></dd></div><div><dt>Reported value</dt><dd>{formatAmount(item.reported_amount_minor, item.reported_currency)}</dd></div><div><dt>Automation</dt><dd>{orchestration ? <><StatusLabel value={orchestration.status} /><span>{humanize(orchestration.stage)}</span></> : "Not started"}</dd></div><div><dt>Updated</dt><dd><time dateTime={item.updated_at}>{formatDate(item.updated_at)}</time></dd></div></dl>
  </article>;
}

function SelectedCasesDrawer({ items, onClose }: { items: CaseInboxItem[]; onClose: () => void }) {
  return <aside className="panel selection-drawer" role="dialog" aria-modal="true" aria-labelledby="selected-cases-title">
    <div className="panel-heading"><div><p className="section-kicker">Read-only review</p><h2 id="selected-cases-title">Selected cases</h2><p className="panel-subtitle">Open a case to inspect its authoritative read model.</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close selected cases">×</button></div>
    <ul className="selection-list">{items.map((item) => <li key={item.case_id}><Link className="case-link" href={`/cases/${encodeURIComponent(item.case_id)}`} onClick={onClose}>{item.case_id}</Link><span>{humanize(item.incident_type)} · {humanize(item.state)}</span></li>)}</ul>
    <div className="selection-drawer__footer"><button type="button" className="button button--quiet" onClick={onClose}>Close</button></div>
  </aside>;
}

function SummaryMetric({ label, value, detail, tone }: { label: string; value: number; detail: string; tone?: "attention" }) {
  return <div className={tone ? "summary-metric summary-metric--attention" : "summary-metric"}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function StatusLabel({ value }: { value: string }) {
  const tone = value.includes("attention") || value.includes("escalat") ? "state-label--uncertain" : value.includes("completed") || value.includes("contained") ? "state-label--legitimate" : value.includes("running") ? "state-label--replay" : "";
  return <span className={`state-label ${tone}`}><span aria-hidden="true">{value === "running" ? "◌" : value.includes("attention") ? "!" : "·"}</span>{humanize(value)}</span>;
}

function IncidentIntakePanel({ tenantId, onClose, onAccepted }: { tenantId: string; onClose: () => void; onAccepted: (caseId: string | null) => void }) {
  const [source, setSource] = useState("merchant_portal");
  const [incidentType, setIncidentType] = useState("account_takeover");
  const [occurredAt, setOccurredAt] = useState("");
  const [narrative, setNarrative] = useState("");
  const [customerReference, setCustomerReference] = useState("");
  const [accountReference, setAccountReference] = useState("");
  const [orderReference, setOrderReference] = useState("");
  const [paymentReference, setPaymentReference] = useState("");
  const [externalReference, setExternalReference] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    setIsError(false);
    try {
      const reportedAmountMinor = amount.trim() ? parseAmountToMinor(amount, currency) : undefined;
      if (amount.trim() && reportedAmountMinor === undefined) throw new Error("Enter a valid non-negative amount with the selected currency.");
      if (!amount.trim() && currency !== "INR") throw new Error("Clear the currency or enter an amount; amount and currency must travel together.");
      const result = await submitIncidentIntake(tenantId, {
        source,
        incidentType,
        occurredAt: new Date(occurredAt).toISOString(),
        narrative: narrative.trim(),
        customerReference: customerReference.trim() || undefined,
        accountReference: accountReference.trim() || undefined,
        orderReference: orderReference.trim() || undefined,
        paymentReference: paymentReference.trim() || undefined,
        externalReference: externalReference.trim() || undefined,
        reportedAmountMinor,
        reportedCurrency: reportedAmountMinor === undefined ? undefined : currency,
      });
      onAccepted(result.case_id ?? null);
    } catch (reason) {
      setIsError(true);
      setMessage(reason instanceof ReclaimApiError || reason instanceof Error ? reason.message : "The incident could not be accepted.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <aside className="panel intake-panel" id="intake-panel" role="dialog" aria-modal="true" aria-labelledby="intake-title">
      <div className="panel-heading"><div><p className="section-kicker">Authoritative intake</p><h2 id="intake-title">Report an incident</h2><p className="panel-subtitle">Required fields are stored with immutable raw evidence.</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close intake form">×</button></div>
      <form className="intake-form" onSubmit={(event) => void submit(event)}>
        <label>Source<input required value={source} onChange={(event) => setSource(event.target.value)} maxLength={100} /></label>
        <label>Incident type<select required value={incidentType} onChange={(event) => setIncidentType(event.target.value)}><option value="account_takeover">Account takeover</option><option value="unauthorized_payment">Unauthorized payment</option><option value="refund_abuse">Refund abuse</option><option value="chargeback">Chargeback</option><option value="policy_abuse">Policy abuse</option><option value="other">Other</option></select></label>
        <label>When did it occur?<input required type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} /></label>
        <label>Narrative<textarea required minLength={1} value={narrative} onChange={(event) => setNarrative(event.target.value)} maxLength={20000} placeholder="Describe what the merchant observed. This is retained as raw evidence." /></label>
        <fieldset><legend>References <span>(optional)</span></legend><div className="intake-two-col"><label>Customer<input value={customerReference} onChange={(event) => setCustomerReference(event.target.value)} /></label><label>Account<input value={accountReference} onChange={(event) => setAccountReference(event.target.value)} /></label><label>Order<input value={orderReference} onChange={(event) => setOrderReference(event.target.value)} /></label><label>Payment<input value={paymentReference} onChange={(event) => setPaymentReference(event.target.value)} /></label><label>External ref.<input value={externalReference} onChange={(event) => setExternalReference(event.target.value)} /></label></div></fieldset>
        <fieldset><legend>Reported value <span>(optional, unverified)</span></legend><div className="intake-two-col"><label>Amount<input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" /></label><label>Currency<select value={currency} onChange={(event) => setCurrency(event.target.value)}>{Object.keys(CURRENCY_MINOR_UNITS).sort().map((code) => <option key={code}>{code}</option>)}</select></label></div><p className="field-help">Stored as integer minor units. This is a report, not a verified loss.</p></fieldset>
        {message ? <p className={isError ? "form-message form-message--error" : "form-message"} role={isError ? "alert" : "status"}>{message}</p> : null}
        <div className="intake-actions"><button type="button" className="button button--quiet" onClick={onClose}>Cancel</button><button type="submit" className="button button--primary" disabled={submitting}>{submitting ? "Accepting…" : "Accept incident"}</button></div>
      </form>
    </aside>
  );
}

function EmptyInbox({ onCreate }: { onCreate: () => void }) {
  return <div className="empty-state inbox-empty"><span className="empty-state__mark" aria-hidden="true">⌁</span><div><h3>No matching cases</h3><p>Try clearing a filter, or create a new incident intake to begin the authoritative workflow.</p><button type="button" className="button button--quiet" onClick={onCreate}>Open intake form</button></div></div>;
}

function InboxError({ error, onRetry }: { error: ReclaimApiError; onRetry: () => void }) {
  const title = error.kind === "availability" || error.kind === "network"
    ? "API unavailable"
    : error.kind === "permission"
      ? "Case access is not authorized"
      : "Could not load the case inbox";
  return <div className="empty-state inbox-error"><span className="empty-state__mark" aria-hidden="true">!</span><div><h3>{title}</h3><p>{error.message}</p><button type="button" className="button button--quiet" onClick={onRetry}>Try again</button></div></div>;
}

function InboxSkeleton() {
  return <div className="inbox-skeleton" aria-label="Loading cases" aria-busy="true"><span /><span /><span /><span /></div>;
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatAmount(amountMinor: number | null | undefined, currency: string | null | undefined) {
  if (amountMinor === null || amountMinor === undefined || !currency) return "Reported value unverified";
  const units = CURRENCY_MINOR_UNITS[currency] ?? 2;
  return new Intl.NumberFormat("en", { style: "currency", currency, minimumFractionDigits: units, maximumFractionDigits: units }).format(amountMinor / 10 ** units) + " unverified";
}

function parseAmountToMinor(value: string, currency: string) {
  const units = CURRENCY_MINOR_UNITS[currency] ?? 2;
  const normalized = value.trim();
  const match = normalized.match(/^(?:0|[1-9]\d*)(?:\.(\d+))?$/);
  if (!match || (match[1] && match[1].length > units)) return undefined;
  const whole = normalized.split(".")[0];
  const fraction = (match[1] ?? "").padEnd(units, "0");
  const result = Number(`${whole}${fraction}` || "0");
  return Number.isSafeInteger(result) ? result : undefined;
}
