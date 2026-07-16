import { useState } from "react";

/** Reveals a long list progressively instead of rendering it all at once - the
 * dashboard's own single-page-with-brief-data pattern. Purely client-side over
 * an array that's already in memory: it does NOT issue a new query, so "more"
 * tops out at whatever the initial fetch already brought back (see the `limit`
 * on each query in useDashboardData / useStrategyLab). Resets are intentionally
 * NOT handled here - a fresh poll can grow `items` under an unchanged `count`,
 * which just means more becomes revealable, never fewer already-shown rows. */
export function useShowMore<T>(items: T[], initial: number, step: number) {
  const [count, setCount] = useState(initial);
  const visible = items.slice(0, count);
  return {
    visible,
    shown: visible.length,
    total: items.length,
    hasMore: count < items.length,
    showMore: () => setCount((c) => Math.min(items.length, c + step)),
  };
}
