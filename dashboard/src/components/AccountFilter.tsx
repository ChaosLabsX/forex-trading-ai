import type { Account } from "../types";

type Props = {
  accounts: Account[];
  selected: string | null;
  onSelect: (key: string) => void;
};

/** Scope selector for everything money-related.
 *
 * There is deliberately no "All" option: summing demo play money with real
 * money produces a number that means nothing, and a P&L figure you can't trust
 * is worse than no figure. You are always looking at exactly one account. */
export function AccountFilter({ accounts, selected, onSelect }: Props) {
  if (accounts.length < 2) return null;

  return (
    <div className="acct-filter" role="tablist" aria-label="Account">
      {accounts.map((a) => (
        <button
          key={a.key}
          role="tab"
          aria-selected={selected === a.key}
          className={`acct-pill ${selected === a.key ? "is-active" : ""} ${
            a.account_type === "live" ? "is-live" : ""
          }`}
          onClick={() => onSelect(a.key)}
        >
          {a.account_type.toUpperCase()}
          <span className="acct-pill-label">{a.label}</span>
        </button>
      ))}
    </div>
  );
}
