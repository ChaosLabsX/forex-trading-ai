export type AIReview = {
  approved: boolean;
  confidence: number;
  rationale: string;
};

export type Signal = {
  id: number;
  strategy_name: string;
  symbol: string;
  fired: boolean;
  direction: "LONG" | "SHORT" | null;
  timeframe: string | null;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  reason: string;
  risk_approved: boolean | null;
  risk_reason: string | null;
  created_at: string;
  account_key: string;
  ai_reviews: AIReview[];
};

export type Trade = {
  id: number;
  mt5_ticket: string;
  strategy_name: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  lot_size: number;
  entry_price: number;
  stop_loss: number | null;
  take_profit: number | null;
  status: "OPEN" | "CLOSED";
  realized_pnl: number | null;
  opened_at: string;
  closed_at: string | null;
  account_key: string;
  /** Stop as first placed - never rewritten by trailing, so R stays computable. */
  initial_stop_loss: number | null;
  /** Account currency at risk if the initial stop had been hit. */
  risk_amount: number | null;
};

export type Heartbeat = {
  id: number;
  status: string;
  broker_connected: boolean;
  detail: string | null;
  created_at: string;
  account_key: string;
};

export type CommandType = "pause" | "resume" | "emergency_close_all";

export type Readiness = "not_ready" | "almost_ready" | "ready";

export type Account = {
  id: number;
  key: string;
  label: string;
  broker: string;
  account_type: "demo" | "live";
  enabled: boolean;
};

export type Strategy = {
  id: number;
  name: string;
  display_name: string | null;
  description: string | null;
  readiness: Readiness;
  readiness_reason: string | null;
  readiness_updated_at: string | null;
  retired: boolean;
};

export type StrategyAccount = {
  id: number;
  strategy_name: string;
  account_key: string;
  enabled: boolean;
  live_override: boolean;
};

/** One evaluator snapshot for a (strategy, account) pair. */
export type StrategyEvaluation = {
  id: number;
  strategy_name: string;
  account_key: string;
  computed_at: string;
  trades_count: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  expectancy_r: number | null;
  ci_low: number | null;
  ci_high: number | null;
  profit_factor: number | null;
  avg_win_r: number | null;
  avg_loss_r: number | null;
  max_drawdown_r: number | null;
  longest_loss_streak: number | null;
  total_net_pnl: number | null;
  verdict: Readiness;
  verdict_reason: string | null;
};
