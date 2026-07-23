-- The join key the AI-review track record was missing.
--
-- ai_reviews.signal_id -> signals.id records Claude's shadow-mode opinion of a
-- fired signal (migration 0006). But `trades` had no link back to the signal that
-- produced it, so there was no way to join an AI verdict to the trade's realized
-- outcome - which is the entire point of shadow mode ("build a track record worth
-- trusting later", per engine/plugins/ai/claude_ai_provider.py). The record was
-- unscoreable as built. This adds the missing key.
--
-- Nullable on purpose: trades opened before this migration, or by hand, or via the
-- orphan-recovery path where no signal row exists, simply carry NULL. on delete set
-- null keeps a trade's history intact even if its signal row is ever removed.
--
-- Table-level grants on `trades` already cover new columns (service_role writes,
-- authenticated reads), so no new grant is needed.

alter table public.trades
    add column if not exists signal_id bigint
    references public.signals (id) on delete set null;

create index if not exists trades_signal_id_idx on public.trades (signal_id);

comment on column public.trades.signal_id is
    'The signal (signals.id) this trade was opened from. Joins a trade''s realized outcome to its AI review (ai_reviews.signal_id). NULL for hand-opened, pre-migration, or orphan-recovered trades.';
