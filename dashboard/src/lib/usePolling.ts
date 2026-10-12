import { useEffect } from "react";

/** Calls `refresh` now, every `ms` while the page is visible, and once more the
 * moment it becomes visible again.
 *
 * Every dashboard poll used to be a bare setInterval, which keeps firing in a
 * background tab - throttled to about once a minute, but never stopped. A
 * dashboard left open in a tab nobody was looking at re-downloaded up to 1,000
 * trades and 500 evaluation rows on a loop, and that is most of what pushed the
 * Supabase organization over its free-plan quota (2026-10). Pausing while hidden
 * costs nothing: the data is refreshed the instant the tab is looked at. */
export function usePolling(refresh: () => void, ms: number, deps: unknown[] = []) {
  useEffect(() => {
    const visible = () => document.visibilityState === "visible";
    refresh();
    const interval = setInterval(() => {
      if (visible()) refresh();
    }, ms);
    const onVisibility = () => {
      if (visible()) refresh();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ms, ...deps]);
}
