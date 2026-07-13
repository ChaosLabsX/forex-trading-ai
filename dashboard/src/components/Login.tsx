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

  return (
    <div className="gate">
      <div className="gate-card">
        <img src={logoUrl} className="gate-logo" alt="Forex AI logo" />
        <h1>Forex AI</h1>
        <p className="gate-sub">Private trading dashboard. Sign in to continue.</p>
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
