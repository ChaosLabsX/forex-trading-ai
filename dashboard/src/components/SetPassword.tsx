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
      setMessage("Password updated.");
      setPassword("");
    }
  }

  return (
    <form className="account-body" onSubmit={handleSubmit}>
      <p className="account-hint">
        Change the password you sign in with (also needed once after following an invite or reset
        email link).
      </p>
      <input
        type="password"
        placeholder="New password"
        autoComplete="new-password"
        minLength={6}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <button className="btn" type="submit" disabled={submitting}>
        {submitting ? "Saving..." : "Update password"}
      </button>
      {message && <p className="form-ok">{message}</p>}
      {error && <p className="form-error">{error}</p>}
    </form>
  );
}
