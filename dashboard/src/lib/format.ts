const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function fmtDateTime(iso: string): string {
  return dateTimeFmt.format(new Date(iso));
}

/** Signed money, e.g. "+$0.10" / "−$1.20" / "$0.00" (demo account is USD). */
export function fmtMoney(value: number): string {
  if (value === 0) return "$0.00";
  const sign = value > 0 ? "+" : "−";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

export function fmtPrice(value: number): string {
  // FX quotes carry 3-5 decimals depending on the pair; show what's there.
  return String(value);
}

export function fmtAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}
