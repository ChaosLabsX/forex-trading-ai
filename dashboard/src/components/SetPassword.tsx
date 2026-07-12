import { useState } from "react";
import { supabase } from "../lib/supabase";

export function SetPassword() {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setMessage(null);
    const { error } = await supabase.auth.updateUser({ password });
    setSubmitting(false);
    if (error) {
      setError(error.message);
    } else {
      setMessage("Password set - use it to sign in next time.");
      setPassword("");
    }
  }

  return (
    <div className="card">
      <h2>Set password</h2>
      <p className="muted">
        Needed once after following an invite/reset email link - sets the password you'll sign in
        with going forward.
      </p>
      <form onSubmit={handleSubmit}>
        <input
          type="password"
          placeholder="New password"
          minLength={6}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Saving..." : "Set password"}
        </button>
        {message && <p className="status-good">{message}</p>}
        {error && <p className="status-bad">{error}</p>}
      </form>
    </div>
  );
}
