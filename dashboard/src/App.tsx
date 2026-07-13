import { Login } from "./components/Login";
import { Dashboard } from "./components/Dashboard";
import { useAuth } from "./lib/useAuth";

function App() {
  const { session, loading } = useAuth();

  if (loading) {
    return (
      <div className="gate">
        <div className="spinner" aria-label="Loading" />
      </div>
    );
  }

  // Signed out: nothing but the gate. (Matching RLS change - anon has no
  // read access to any monitoring table, so this is enforced server-side
  // too, not just visually.)
  if (!session) return <Login />;

  return <Dashboard session={session} />;
}

export default App;
