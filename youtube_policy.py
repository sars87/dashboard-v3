#!/usr/bin/env python3
import argparse, datetime as dt, ipaddress, json, os, sqlite3, subprocess, sys, time

GRAVITY = "/etc/pihole/gravity.db"
CONFIG = os.environ.get("YOUTUBE_POLICY_CONFIG", "/home/saif/.dashboard_youtube_policy.json")
GROUP_NAME = "YouTube_Block"
GROUP_DESC = "Dashboard YouTube blocking policy"
DOMAINS = ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "googlevideo.com", "youtubei.googleapis.com", "ytimg.com"]


def ensure_parent():
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)


def load_config():
    base = {"mode": "all", "groups": [], "ips": [], "schedule_enabled": False,
            "start": "00:00", "end": "00:00", "days": [0,1,2,3,4,5,6], "manual_enabled": False}
    try:
        with open(CONFIG) as f: base.update(json.load(f))
    except (OSError, ValueError, TypeError): pass
    return base


def save_config(c):
    ensure_parent()
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f: json.dump(c, f, indent=2)
    os.replace(tmp, CONFIG)
    try: os.chmod(CONFIG, 0o640)
    except OSError: pass


def db():
    con = sqlite3.connect(GRAVITY, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def table_columns(con, table):
    safe_table = str(table).replace("'", "''")
    return {r[1] for r in con.execute("PRAGMA table_info('%s')" % safe_table)}


def ensure_policy(con):
    cols = table_columns(con, "group")
    row = con.execute("SELECT id FROM 'group' WHERE name=?", (GROUP_NAME,)).fetchone()
    if row: gid = int(row[0])
    else:
        con.execute("INSERT INTO 'group'(enabled,name,description) VALUES(1,?,?)", (GROUP_NAME, GROUP_DESC))
        gid = int(con.execute("SELECT id FROM 'group' WHERE name=?", (GROUP_NAME,)).fetchone()[0])
    dl_cols = table_columns(con, "domainlist")
    for domain in DOMAINS:
        row = con.execute("SELECT id FROM domainlist WHERE domain=? AND type=1", (domain,)).fetchone()
        if row: did = int(row[0])
        else:
            fields = ["domain", "type", "enabled", "comment"]
            vals = [domain, 1, 1, "Dashboard YouTube policy"]
            fields = [f for f in fields if f in dl_cols]
            mapping = {"domain": domain, "type": 1, "enabled": 1, "comment": "Dashboard YouTube policy"}
            vals = [mapping[f] for f in fields]
            con.execute("INSERT INTO domainlist(%s) VALUES(%s)" % (",".join(fields), ",".join("?" for _ in fields)), vals)
            did = int(con.execute("SELECT id FROM domainlist WHERE domain=? AND type=1", (domain,)).fetchone()[0])
        con.execute("INSERT OR IGNORE INTO domainlist_by_group(domainlist_id,group_id) VALUES(?,?)", (did, gid))
    return gid


def valid_ip(value):
    try: ipaddress.ip_address(str(value)); return str(value)
    except ValueError: return None


def client_ids_for_ips(con, ips):
    ips = [valid_ip(x) for x in ips]
    ips = [x for x in ips if x]
    if not ips: return []
    cols = table_columns(con, "client")
    ids = []
    for ip in ips:
        row = con.execute("SELECT id FROM client WHERE ip=?", (ip,)).fetchone()
        if not row:
            fields = [x for x in ("ip", "name", "comment") if x in cols]
            vals = {"ip": ip, "name": "Dashboard device " + ip, "comment": "Created by YouTube policy"}
            con.execute("INSERT INTO client(%s) VALUES(%s)" % (",".join(fields), ",".join("?" for _ in fields)), [vals[x] for x in fields])
            row = con.execute("SELECT id FROM client WHERE ip=?", (ip,)).fetchone()
        ids.append(int(row[0]))
    return ids


def apply_policy(force=None):
    c = load_config()
    now = dt.datetime.now()
    enabled = c.get("manual_enabled", False) if force is None else bool(force)
    if force is None and c.get("schedule_enabled"):
        days = {int(x) for x in c.get("days", []) if str(x).isdigit()}
        start = str(c.get("start", "00:00")); end = str(c.get("end", "00:00"))
        try:
            sh, sm = map(int, start.split(":")); eh, em = map(int, end.split(":"))
            cur = now.hour * 60 + now.minute; a = sh * 60 + sm; b = eh * 60 + em
            in_window = now.weekday() in {(d-1) % 7 for d in days} and ((a <= cur < b) if a < b else (cur >= a or cur < b))
            enabled = in_window
        except (ValueError, TypeError): enabled = False
    with db() as con:
        gid = ensure_policy(con)
        mode = c.get("mode", "all")
        if mode == "all":
            targets = [0]
        elif mode == "groups":
            targets = [int(x) for x in c.get("groups", []) if str(x).isdigit() and int(x) > 0]
        else:
            ids = client_ids_for_ips(con, c.get("ips", []))
            con.execute("DELETE FROM client_by_group WHERE group_id=?", (gid,))
            for cid in ids:
                con.execute("INSERT OR IGNORE INTO client_by_group(client_id,group_id) VALUES(?,?)", (cid, gid))
            targets = [gid]
        con.execute("DELETE FROM domainlist_by_group WHERE domainlist_id IN (SELECT id FROM domainlist WHERE type=1 AND comment='Dashboard YouTube policy')")
        domain_ids = [r[0] for r in con.execute("SELECT id FROM domainlist WHERE type=1 AND comment='Dashboard YouTube policy'").fetchall()]
        for did in domain_ids:
            for target in targets:
                con.execute("INSERT OR IGNORE INTO domainlist_by_group(domainlist_id,group_id) VALUES(?,?)", (did, target))
            con.execute("UPDATE domainlist SET enabled=? WHERE id=?", (1 if enabled else 0, did))
        if mode == "groups":
            con.execute("UPDATE 'group' SET enabled=1 WHERE id=?", (gid,))
            if targets:
                con.execute("UPDATE 'group' SET enabled=? WHERE id IN (%s)" % ",".join("?" for _ in targets), [1 if enabled else 0] + targets)
        elif mode == "ips":
            con.execute("UPDATE 'group' SET enabled=? WHERE id=?", (1 if enabled else 0, gid))
        else:
            con.execute("UPDATE 'group' SET enabled=1 WHERE id=?", (gid,))
        con.commit()
    try: subprocess.run(["pihole", "reloadlists"], timeout=30, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired): pass
    c["effective_enabled"] = bool(enabled); c["updated_at"] = now.isoformat(timespec="seconds"); save_config(c)
    return c


def status():
    c = load_config()
    with db() as con:
        gid = ensure_policy(con); row = con.execute("SELECT enabled FROM 'group' WHERE id=?", (gid,)).fetchone()
        c["group_id"] = gid; c["group_enabled"] = bool(row and row[0]); c["client_count"] = con.execute("SELECT count(*) FROM client_by_group WHERE group_id=?", (gid,)).fetchone()[0]
    return c


def main():
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init"); sub.add_parser("status"); a = sub.add_parser("apply"); a.add_argument("--force", choices=["on","off"])
    args = p.parse_args()
    if args.cmd == "init": ensure_policy(db()); apply_policy(); return
    if args.cmd == "status": print(json.dumps(status())); return
    print(json.dumps(apply_policy(None if not args.force else args.force == "on")))

if __name__ == "__main__": main()
