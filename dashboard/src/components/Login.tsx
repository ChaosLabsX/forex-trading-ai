import { useState } from "react";
import { useAuth } from "../lib/useAuth";

const logoUrl = `${import.meta.env.BASE_URL}pwa-192x192.png`;

export function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const { error } = await signIn(email, password);
    setSubmitting(false);
    if (error) setError(error.message);
  }

  // This page is the ONLY thing an unauthenticated crawler ever sees, so it is
  // the whole basis of any Safe Browsing verdict. Keep it a neutral identity:
  // no broker name, no platform name, no "Forex" - nothing a classifier can read
  // as a fake broker login. ("Forex AI" branding lives behind the login, in the
  // signed-in app.)
  return (
    <div className="gate">
      <div className="gate-card">
        <img src={logoUrl} className="gate-logo" alt="" />
        <h1>Strategy Lab</h1>
        <p className="gate-sub">Private research dashboard. Sign in to continue.</p>
        <form className="gate-form" onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="Email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting ? "Signing in..." : "Sign in"}
          </button>
          {error && <p className="form-error">{error}</p>}
        </form>
      </div>
    </div>
  );
}
