-- Phase 5: Claude's shadow-mode review of each fired signal. Logged
-- alongside the signal, never gating execution yet - lets rules-only vs
-- AI-reviewed outcomes be compared later (PLAN.md's Phase 5 exit condition).

create table if not exists public.ai_reviews (
    id bigint generated always as identity primary key,
    signal_id bigint references public.signals (id) on delete cascade,
    model text not null,
    approved boolean not null,
    confidence double precision not null,
    rationale text not null,
    created_at timestamptz not null default now()
);

create index if not exists ai_reviews_signal_id_idx on public.ai_reviews (signal_id);

alter table public.ai_reviews enable row level security;

grant all on public.ai_reviews to service_role;
grant select on public.ai_reviews to anon;

create policy "anon read ai_reviews" on public.ai_reviews for select to anon using (true);
