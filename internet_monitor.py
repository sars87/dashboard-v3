#!/usr/bin/env python3
"""Persistent local internet outage monitor for dashboard-v3.

The monitor deliberately uses short TCP probes and a small JSON state file. It
never depends on the dashboard process or a browser, so outages are recorded
while nobody is logged in and survive dashboard restarts.
"""
import json
import os
import socket
import time
from datetime import datetime

STATE_FILE = os.environ.get(
    "DASHBOARD_INTERNET_STATE_FILE",
    "/home/saif/.dashboard_internet_outages.json",
)
CHECK_INTERVAL = max(5, int(os.environ.get("DASHBOARD_INTERNET_CHECK_INTERVAL", "15")))
MAX_HISTORY = 200
PROBES = (("1.1.1.1", 53), ("8.8.8.8", 53))


def now_ts():
    return time.time()


def local_text(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if isinstance(value, dict):
            value.setdefault("version", 1)
            value.setdefault("current", None)
            value.setdefault("outages", [])
            return value
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return {"version": 1, "current": None, "outages": []}


def save_state(state):
    directory = os.path.dirname(STATE_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = STATE_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, STATE_FILE)
    try:
        os.chmod(STATE_FILE, 0o600)
    except OSError:
        pass


def probe_internet():
    """Return True when at least one independent DNS endpoint is reachable."""
    for host, port in PROBES:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            continue
    return False


def begin_outage(state, ts):
    current = state.get("current")
    if not isinstance(current, dict) or not current.get("started_ts"):
        state["current"] = {
            "started_ts": ts,
            "started_at": local_text(ts),
        }
        save_state(state)


def finish_outage(state, ts):
    current = state.get("current")
    if not isinstance(current, dict) or not current.get("started_ts"):
        return
    started = float(current["started_ts"])
    ended = max(ts, started)
    outage = {
        "started_ts": started,
        "ended_ts": ended,
        "started_at": current.get("started_at") or local_text(started),
        "ended_at": local_text(ended),
        "duration_seconds": int(round(ended - started)),
    }
    history = state.setdefault("outages", [])
    history.insert(0, outage)
    state["outages"] = history[:MAX_HISTORY]
    state["current"] = None
    save_state(state)


def main():
    state = load_state()
    previous = None
    while True:
        online = probe_internet()
        ts = now_ts()
        state["online"] = online
        state["checked_at"] = ts
        if online:
            if previous is False:
                finish_outage(state, ts)
            elif isinstance(state.get("current"), dict):
                # A previous monitor process may have exited while the link was
                # already restored; close that stale interval on the first good probe.
                finish_outage(state, ts)
        else:
            begin_outage(state, ts)
        # Persist the latest probe even while the connection remains stable, so
        # dashboard page loads can answer instantly from local disk.
        save_state(state)
        previous = online
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
