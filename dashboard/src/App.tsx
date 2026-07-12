import { EngineHealth } from "./components/EngineHealth";
import { OpenTrades } from "./components/OpenTrades";
import { TradeHistory } from "./components/TradeHistory";
import { SignalsFeed } from "./components/SignalsFeed";
import { Login } from "./components/Login";
import { Controls } from "./components/Controls";
import { useAuth } from "./lib/useAuth";

function App() {
  const { session, loading } = useAuth();

  return (
    <div className="app">
      <header>
        <h1>MT5 + IC Markets Trading Automation</h1>
      </header>

      <EngineHealth />

      {!loading && (session ? <Controls session={session} /> : <Login />)}

      <OpenTrades />
      <TradeHistory />
      <SignalsFeed />
    </div>
  );
}

export default App;
