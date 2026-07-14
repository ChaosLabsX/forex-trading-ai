import { useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";

/** Full-width alert shown only while the engine reports it's paused. Loud on
 * purpose: an accidental pause is easy to leave running unnoticed otherwise.
 * Includes a one-click resume so it can be undone without scrolling to the
 * Controls section. */
export function PausedBanner({ session }: { session: Session }) {
  const [pending, setPending] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function resume() {
    setPending(true);
    setNote(null);
    const { error } = await supabase
      .from("commands")
      .insert({ command_type: "resume", created_by: session.user.id });
    setPending(false);
    setNote(
      error
        ? `Failed: ${error.message}`
        : "Resume sent - the engine picks it up within a few seconds."
    );
  }

  return (
    <div className="banner banner-paused" role="alert">
      <span className="dot dot-warn banner-dot" aria-hidden="true" />
      <div className="banner-text">
        <strong>Trading is paused.</strong> The engine is still running and
        monitoring the market, but it will not open new trades until you resume.
      </div>
      <button className="btn" disabled={pending} onClick={resume}>
        {pending ? "Resuming…" : "Resume trading"}
      </button>
      {note && <span className="banner-note">{note}</span>}
    </div>
  );
}
