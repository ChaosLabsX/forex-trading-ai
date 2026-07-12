import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anonKey) {
  throw new Error("VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY must be set (see .env.example)");
}

// This is the anon key, safe to ship in a static bundle - RLS policies are
// the real access boundary, not key secrecy. See docs/architecture.md.
export const supabase = createClient(url, anonKey);
