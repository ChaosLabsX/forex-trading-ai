"""When the FX market opens and closes, and how to say it in Jakarta time.

IC Markets runs on the New-York-close convention: server midnight is 17:00 in
New York, so the server day IS the trading day. FX trades from Monday 00:00 to
Friday 24:00 server time - Sunday 17:00 to Friday 17:00 in New York. The
server's UTC offset (+2 winter, +3 summer) comes from the same rule the engine
already uses to stamp every bar (mt5_time.ny_close_offset_seconds), so these
times follow US daylight saving without a timezone database.

A schedule, not a tick watcher, on purpose: the alert can name the NEXT event
(a tick watcher cannot know when the market will reopen), and a quiet minute
on a Tuesday is never mistaken for a close. What it does not know: one-off
holiday closures (25 Dec, 1 Jan) and per-symbol session breaks (gold's daily
hour) - it describes the FX week.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.plugins.brokers.mt5_time import ny_close_offset_seconds

# Indonesia's western time: UTC+7 all year, no daylight saving.
JAKARTA = timezone(timedelta(hours=7), "WIB")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _server(utc: datetime) -> datetime:
    """Broker server wall-clock time (naive) at a UTC instant."""
    return (utc + timedelta(seconds=ny_close_offset_seconds(utc))).replace(tzinfo=None)


def _to_utc(server: datetime) -> datetime:
    """A server wall-clock time back to UTC. The offset depends on the instant,
    so try both and keep the one that agrees with itself."""
    for hours in (3, 2):
        utc = (server - timedelta(hours=hours)).replace(tzinfo=timezone.utc)
        if ny_close_offset_seconds(utc) == hours * 3600:
            return utc
    raise ValueError(f"no consistent UTC instant for server time {server}")


def is_open(utc: datetime) -> bool:
    """FX trades Monday to Friday by the server's calendar."""
    return _server(utc).weekday() < 5


def _next_server_midnight(utc: datetime, weekday: int) -> datetime:
    """The next server midnight that starts `weekday` (0 = Monday), strictly
    after `utc`, as UTC."""
    server = _server(utc)
    midnight = server.replace(hour=0, minute=0, second=0, microsecond=0)
    days = (weekday - server.weekday()) % 7 or 7
    return _to_utc(midnight + timedelta(days=days))


def next_open(utc: datetime) -> datetime:
    """Next Monday 00:00 server - Sunday 17:00 New York."""
    return _next_server_midnight(utc, 0)


def next_close(utc: datetime) -> datetime:
    """Next Saturday 00:00 server - Friday 17:00 New York."""
    return _next_server_midnight(utc, 5)


def week_start(close_utc: datetime) -> datetime:
    """The Monday 00:00 server open that began the trading week `close_utc`
    falls in or ends. Snapped to the midnight, never `close - 5 days`: the loop
    notices a close seconds or minutes after it happens, and a start that
    drifted with it would drop the week's first trades from the summary."""
    server = _server(close_utc)
    midnight = server.replace(hour=0, minute=0, second=0, microsecond=0)
    return _to_utc(midnight - timedelta(days=server.weekday()))


def jakarta(utc: datetime) -> str:
    """'5:00 AM - 24 Nov': Jakarta time, 12-hour clock, no year. Built by hand
    rather than strftime, whose %b is locale-dependent on Windows."""
    local = utc.astimezone(JAKARTA)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} - {local.day} {_MONTHS[local.month - 1]}"
