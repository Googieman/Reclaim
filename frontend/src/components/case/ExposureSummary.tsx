import type { ExposureSummaryData } from "@/lib/api";

interface ExposureSummaryProps {
  readonly exposure: ExposureSummaryData;
}

export function ExposureSummary({ exposure }: ExposureSummaryProps) {
  const ledgers = exposure.by_currency.length > 0 ? exposure.by_currency : [exposure];

  return (
    <section className="panel exposure-panel" aria-labelledby="exposure-title">
      <div className="panel-heading">
        <p className="section-kicker">Authoritative ledger</p>
        <h2 id="exposure-title">Financial exposure</h2>
        <p className="panel-subtitle">Trusted integer minor units · calculation {exposure.calculation_version}</p>
      </div>
      {ledgers.map((ledger) => (
        <div className="exposure-ledger" key={ledger.currency}>
          <div className="exposure-primary">
            <span>Remaining Exposure</span>
            <strong>{formatMinor(ledger.remaining_exposure_minor, ledger.currency)}</strong>
            <small>Value still at risk</small>
          </div>
          <dl className="exposure-rows">
            <ExposureRow label="Recoverable Exposure" value={ledger.recoverable_value_minor} currency={ledger.currency} emphasis />
            <ExposureRow label="Contained Value" value={ledger.contained_value_minor} currency={ledger.currency} />
            <ExposureRow label="Gross Exposure" value={ledger.gross_exposure_minor} currency={ledger.currency} />
            <ExposureRow label="Legitimate Value Disrupted" value={ledger.legitimate_value_disrupted_minor} currency={ledger.currency} />
            <ExposureRow label="Irreversible Loss" value={ledger.irreversible_loss_minor} currency={ledger.currency} />
          </dl>
          <p className="provenance-note">
            Sources: {ledger.source_references.length > 0 ? ledger.source_references.join(" · ") : "No source references supplied"}
          </p>
        </div>
      ))}
    </section>
  );
}

function ExposureRow({ label, value, currency, emphasis = false }: { label: string; value: number; currency: string; emphasis?: boolean }) {
  return (
    <div className={emphasis ? "exposure-row exposure-row--emphasis" : "exposure-row"}>
      <dt>{label}</dt>
      <dd>{formatMinor(value, currency)}</dd>
    </div>
  );
}

function formatMinor(value: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(value / 100);
}
