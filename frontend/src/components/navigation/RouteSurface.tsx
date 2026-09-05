import Link from "next/link";
import { AppNavigation } from "./AppNavigation";

export function RouteSurface({
  tenantId,
  title,
  description,
  sourceNote,
}: {
  tenantId: string;
  title: string;
  description: string;
  sourceNote: string;
}) {
  return (
    <div className="app-shell route-surface-shell">
      <AppNavigation tenantId={tenantId} />
      <div className="main-column">
        <header className="top-bar">
          <div className="top-bar__identity"><span className="mobile-brand-mark" aria-hidden="true">R</span><span>Incident command</span></div>
          <div className="top-bar__context"><span className="context-label">Merchant</span><strong>Tenant operations</strong><span className="context-divider" aria-hidden="true" /><span className="mode-badge mode-badge--live"><span className="mode-badge__mark" aria-hidden="true">●</span>LIVE READ</span></div>
          <div className="operator-identity"><span className="operator-dot" aria-hidden="true" />Reviewer session</div>
        </header>
        <main className="route-surface" aria-labelledby="route-surface-title">
          <div className="route-surface__intro">
            <p className="section-kicker">Operator workspace</p>
            <h1 id="route-surface-title">{title}</h1>
            <p className="case-context">{description}</p>
          </div>
          <section className="panel route-surface__panel" aria-labelledby="route-source-title">
            <span className="route-surface__mark" aria-hidden="true">—</span>
            <div>
              <h2 id="route-source-title">No collection read model connected</h2>
              <p>{sourceNote}</p>
              <p className="route-surface__honesty">The interface will show records here when the authoritative tenant-scoped API exposes them. Nothing is synthesized in the meantime.</p>
              <Link className="button button--quiet route-surface__link" href="/cases">Open incident inbox</Link>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}
