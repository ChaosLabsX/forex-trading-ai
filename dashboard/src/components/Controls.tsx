import { useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import type { CommandType } from "../types";

type Props = {
  session: Session;
  /** Commands are consumed only by the engine running THIS account, so it is
   * never optional - an untargeted command would silently hit whichever engine
   * happened to default to it. */
  accountKey: string;
  accountLabel: string;
};

export function Controls({ session, accountKey, accountLabel }: Props) {
  const [pending, setPending] = useState<CommandType | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function sendCommand(commandType: CommandType) {
    if (commandType === "emergency_close_all") {
      const confirmed = window.confirm(
        `This will immediately close every open position on ${accountLabel}. Are you sure?`
      );
      if (!confirmed) return;
    }

    setPending(commandType);
    setMessage(null);
    const { error } = await supabase.from("commands").insert({
      command_type: commandType,
      created_by: session.user.id,
      account_key: accountKey,
    });
    setPending(null);
    setMessage(
      error
        ? `Failed: ${error.message}`
        : "Command sent - the engine picks it up within a few seconds."
    );
  }

  return (
    <>
      <div className="controls-row">
        <button className="btn" disabled={pending !== null} onClick={() => sendCommand("pause")}>
          Pause trading
        </button>
        <button className="btn" disabled={pending !== null} onClick={() => sendCommand("resume")}>
          Resume trading
        </button>
        <span className="grow" />
        <button
          className="btn btn-danger"
          disabled={pending !== null}
          onClick={() => sendCommand("emergency_close_all")}
        >
          Emergency close all
        </button>
      </div>
      {message && <p className="controls-note">{message}</p>}
    </>
  );
}
