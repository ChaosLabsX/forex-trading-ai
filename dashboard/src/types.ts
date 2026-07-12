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
};

export type Heartbeat = {
  id: number;
  status: string;
  broker_connected: boolean;
  detail: string | null;
  created_at: string;
};

export type CommandType = "pause" | "resume" | "emergency_close_all";
