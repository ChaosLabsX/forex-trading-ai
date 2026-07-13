import type { Signal } from "../types";
import { fmtDateTime } from "../lib/format";

function SignalBadge({ signal }: { signal: Signal }) {
  if (!signal.fired) {
    return <span className="badge badge-muted">no signal</span>;
  }
  const directionBadge = (
    <span className={`badge ${signal.direction === "LONG" ? "badge-long" : "badge-short"}`}>
      {signal.direction === "LONG" ? "▲ LONG" : "▼ SHORT"}
    </span>
  );
  if (signal.risk_approved === false) {
    return (
      <>
        {directionBadge} <span className="badge badge-warn">blocked by risk</span>
      </>
    );
  }
  return directionBadge;
}

function AIBadge({ signal }: { signal: Signal }) {
  const review = signal.ai_reviews?.[0];
  if (!review) return <span className="badge badge-muted">—</span>;
  const pct = Math.round(review.confidence * 100);
  return (
    <details className="ai-details">
      <summary>
        <span
          className={`badge ${review.approved ? "badge-long" : "badge-short"}`}
          title="Claude's shadow-mode second opinion - never blocks a trade"
        >
          {review.approved ? "✓ agrees" : "✕ disagrees"} · {pct}%
        </span>
      </summary>
      <p className="ai-rationale">{review.rationale}</p>
    </details>
  );
}

export function SignalsFeed({ signals }: { signals: Signal[] }) {
  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Recent signals</h2>
        <span className="section-meta">every evaluation, fired or filtered</span>
      </div>
      <div className="card">
        {signals.length === 0 ? (
          <p className="empty">No signals logged yet.</p>
        ) : (
          <table className="rtable">
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Signal</th>
                <th>AI review</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr key={s.id}>
                  <td className="cell-time" data-label="Time">{fmtDateTime(s.created_at)}</td>
                  <td className="cell-sym" data-label="Symbol">{s.symbol}</td>
                  <td data-label="Signal">
                    <SignalBadge signal={s} />
                  </td>
                  <td className="cell-wide" data-label="AI review">
                    <AIBadge signal={s} />
                  </td>
                  <td className="cell-reason cell-wide" data-label="Reason">
                    {s.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
