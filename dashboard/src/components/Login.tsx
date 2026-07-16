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

  // This page is the ONLY thing an unauthenticated crawler ever sees, which
  // makes it the whole basis of Safe Browsing's phishing verdict. Its job is
  // therefore two things at once: log you in, and state plainly what this site
  // is - because "phishing" means impersonation, and the fix for a false
  // impersonation claim is an unambiguous identity. No broker name, no platform
  // name, no "Forex", nothing a classifier can read as a fake broker login.
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
        <p className="gate-note">
          A personal, single-user project for private research. This site is not a broker,
          not a financial service, and is not affiliated with or endorsed by any broker,
          exchange, or trading platform. It offers no accounts, sells nothing, and collects
          no visitor data. Sign-in exists only to keep the owner's own data private.
        </p>
      </div>
    </div>
  );
}
