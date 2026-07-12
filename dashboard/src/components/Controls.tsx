import { useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { useAuth } from "../lib/useAuth";
import type { CommandType } from "../types";

export function Controls({ session }: { session: Session }) {
  const { signOut } = useAuth();
  const [pending, setPending] = useState<CommandType | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function sendCommand(commandType: CommandType) {
    if (commandType === "emergency_close_all") {
      const confirmed = window.confirm(
        "This will immediately close every open position. Are you sure?"
      );
      if (!confirmed) return;
    }

    setPending(commandType);
    setMessage(null);
    const { error } = await supabase
      .from("commands")
      .insert({ command_type: commandType, created_by: session.user.id });
    setPending(null);
    setMessage(error ? `Failed: ${error.message}` : `${commandType} sent - the engine checks in every few seconds.`);
  }

  return (
    <div className="card">
      <div className="controls-header">
        <h2>Controls</h2>
        <button className="link-button" onClick={() => signOut()}>
          Sign out ({session.user.email})
        </button>
      </div>
      <div className="controls-buttons">
        <button disabled={pending !== null} onClick={() => sendCommand("pause")}>
          Pause trading
        </button>
        <button disabled={pending !== null} onClick={() => sendCommand("resume")}>
          Resume trading
        </button>
        <button
          className="danger"
          disabled={pending !== null}
          onClick={() => sendCommand("emergency_close_all")}
        >
          Emergency close all
        </button>
      </div>
      {message && <p className="muted">{message}</p>}
    </div>
  );
}
