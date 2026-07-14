import { useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import type { AccountHealth } from "../lib/useDashboardData";

/** Full-width alert shown only while an engine reports it's paused. Loud on
 * purpose: an accidental pause is easy to leave running unnoticed otherwise.
 * Names the account, because with a demo and a live engine "paused" alone is
 * ambiguous - and includes one-click resume for that specific engine. */
export function PausedBanner({ session, paused }: { session: Session; paused: AccountHealth[] }) {
  const [pending, setPending] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  if (paused.length === 0) return null;

  async function resume(accountKey: string) {
    setPending(accountKey);
    setNote(null);
    const { error } = await supabase.from("commands").insert({
      command_type: "resume",
      created_by: session.user.id,
      account_key: accountKey,
    });
    setPending(null);
    setNote(
      error ? `Failed: ${error.message}` : "Resume sent - the engine picks it up within a few seconds."
    );
  }

  return (
    <>
      {paused.map((h) => (
        <div className="banner banner-paused" role="alert" key={h.account.key}>
          <span className="dot dot-warn banner-dot" aria-hidden="true" />
          <div className="banner-text">
            <strong>Trading is paused on {h.account.label}.</strong> The engine is still running and
            monitoring the market, but it will not open new trades until you resume.
          </div>
          <button
            className="btn"
            disabled={pending === h.account.key}
            onClick={() => resume(h.account.key)}
          >
            {pending === h.account.key ? "Resuming…" : "Resume trading"}
          </button>
          {note && <span className="banner-note">{note}</span>}
        </div>
      ))}
    </>
  );
}
