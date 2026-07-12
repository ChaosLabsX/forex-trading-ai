-- Phase 3: record what the risk engine decided about each fired signal, so a
-- fired-but-not-traded signal is traceable (correlate against `trades` by time).
alter table public.signals add column if not exists risk_approved boolean;
alter table public.signals add column if not exists risk_reason text;
