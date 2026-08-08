
from flask import Flask, request, redirect, session, render_template_string
import os, subprocess, socket, re, json, urllib.request, time
from urllib.parse import urlencode

app = Flask(__name__)
app.secret_key = "Sars87_SECRET_KEY"
PASSWORD = "Sars87"
PIHOLE_PW = "Sars87"          # Pi-hole web/API password (for real-time stats)
PIHOLE_API = "http://127.0.0.1/api"
VERSION = "Dashboard v1.6"
PIHOLE_PAUSE_STATE = "/tmp/pihole_pause_timer.json"

# ==================================================
# HELPERS
# ==================================================
def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
    except:
        return ""

# Simple TTL cache so the 10s auto-refresh doesn't rerun expensive commands.
_CACHE = {}
def cached(key, ttl, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val

def net_counters():
    # rx/tx byte counters for the busiest physical interface, plus a timestamp.
    # The client polls this and computes deltas to show live throughput.
    best = {"iface": "", "rx": 0, "tx": 0, "t": time.time()}
    bestbytes = -1
    try:
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                name, _, data = line.partition(":")
                name = name.strip()
                if name == "lo" or name.startswith(("veth", "docker", "br-", "tailscale", "tun", "wg")):
                    continue
                p = data.split()
                rx, tx = int(p[0]), int(p[8])
                if rx + tx > bestbytes:
                    bestbytes = rx + tx
                    best = {"iface": name, "rx": rx, "tx": tx, "t": time.time()}
    except:
        pass
    return best

def svc(name):
    x = sh(f"systemctl is-active {name}")
    return x if x else "unknown"

def internet():
    try:
        socket.create_connection(("1.1.1.1", 53), 2)
        return True
    except:
        return False

def pihole():
    x = sh("pihole status").lower()
    if "enabled" in x:
        return "Enabled"
    if "disabled" in x:
        return "Disabled"
    return "Unknown"

def pihole_pause_state():
    """Return the timed-disable state, removing it once it has expired."""
    try:
        with open(PIHOLE_PAUSE_STATE) as f:
            ends_at = int(json.load(f)["ends_at"])
        remaining = ends_at - int(time.time())
        if remaining > 0:
            return {"ends_at": ends_at, "remaining": remaining}
        os.remove(PIHOLE_PAUSE_STATE)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        pass
    return None

def clear_pihole_pause_state():
    try:
        os.remove(PIHOLE_PAUSE_STATE)
    except FileNotFoundError:
        pass

def youtube_status():
    x = sh("sudo sqlite3 /etc/pihole/gravity.db \"select enabled from 'group' where name='YouTube_Block';\"").strip()
    if x == "0":
        return "Enabled"
    if x == "1":
        return "Blocked"
    return "Unknown"

def cpu():
    try:
        return int(float(sh("top -bn1 | awk '/Cpu\\(s\\)/ {print $2+$4}'") or 0))
    except:
        return 0

def ram():
    try:
        return int(sh("free | awk '/Mem:/ {print ($3/$2)*100}' | cut -d. -f1") or 0)
    except:
        return 0

def disk():
    try:
        return int(sh("df / | awk 'NR==2 {print $5}'").replace("%", ""))
    except:
        return 0

def temp():
    t = sh("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
    if t.isdigit():
        return round(int(t) / 1000, 1)
    return 0

def uptime():
    return sh("uptime -p").replace("up ", "")

def battery():
    try:
        # Check standard Linux sysfs ACPI battery paths
        bat_path = ""
        for b in ["BAT0", "BAT1", "BAT"]:
            if os.path.exists(f"/sys/class/power_supply/{b}"):
                bat_path = f"/sys/class/power_supply/{b}"
                break
        
        ac_online = False
        for ac in ["AC", "ACAD", "ADP1", "ADP0"]:
            ac_file = f"/sys/class/power_supply/{ac}/online"
            if os.path.exists(ac_file):
                with open(ac_file) as f:
                    if f.read().strip() == "1":
                        ac_online = True
                        break
        
        # If no explicit AC online file, check status
        if not bat_path:
            return {"status": "Plugged (AC)", "percent": 100, "charging": True, "has_battery": False}

        capacity = 100
        cap_file = f"{bat_path}/capacity"
        if os.path.exists(cap_file):
            with open(cap_file) as f:
                capacity = int(f.read().strip() or 100)

        status_str = "Unknown"
        status_file = f"{bat_path}/status"
        if os.path.exists(status_file):
            with open(status_file) as f:
                status_str = f.read().strip()

        is_charging = status_str in ["Charging", "Full"] or ac_online
        
        if is_charging:
            status_text = "Plugged (Charging)" if status_str == "Charging" else ("Plugged (Full)" if status_str == "Full" else "Plugged (AC)")
        else:
            status_text = f"Battery ({capacity}%)"

        return {
            "status": status_text,
            "percent": capacity,
            "charging": is_charging,
            "has_battery": True
        }
    except:
        return {"status": "Plugged (AC)", "percent": 100, "charging": True, "has_battery": False}

def reboot_info():
    return sh("who -b | awk '{print $3\" \"$4}'")

def explain_cron_schedule(sched):
    s = sched.strip()
    parts = s.split()
    if len(parts) != 5:
        return f"Custom schedule: {s} (توقيت مخصص)"
    
    m, h, dom, mon, dow = parts
    
    dow_map = {
        "0": "Sunday (الأحد)", "1": "Monday (الإثنين)", "2": "Tuesday (الثلاثاء)",
        "3": "Wednesday (الأربعاء)", "4": "Thursday (الخميس)", "5": "Friday (الجمعة)",
        "6": "Saturday (السبت)", "7": "Sunday (الأحد)"
    }
    
    # Parse Days of Week
    dow_desc = "Every day (كل يوم)"
    if dow != "*":
        if dow in ["0-4", "1-5"]:
            if dow == "0-4":
                dow_desc = "Sunday to Thursday (من الأحد إلى الخميس - أيام الدوام)"
            else:
                dow_desc = "Monday to Friday (من الإثنين إلى الجمعة)"
        elif "-" in dow:
            p = dow.split("-")
            start = dow_map.get(p[0], p[0])
            end = dow_map.get(p[1], p[1])
            dow_desc = f"From {start} to {end} (من {start} إلى {end})"
        elif "," in dow:
            days = [dow_map.get(d.strip(), d.strip()) for d in dow.split(",")]
            dow_desc = f"On days: {', '.join(days)} (في أيام: {', '.join(days)})"
        else:
            d_name = dow_map.get(dow, dow)
            dow_desc = f"Every week on {d_name} (كل أسبوع يوم {d_name})"

    # Parse Time (Hour & Minute)
    time_desc = ""
    if h == "*" and m == "*":
        time_desc = "Every minute (كل دقيقة)"
    elif h == "*":
        if m.startswith("*/"):
            val = m.split("/")[1]
            time_desc = f"Every {val} minutes of every hour (كل {val} دقائق من كل ساعة)"
        else:
            time_desc = f"At minute {m} of every hour (في الدقيقة {m} من كل ساعة)"
    else:
        # Specific hour(s)
        if h.isdigit() and m.isdigit():
            hr = int(h)
            mn = int(m)
            am_pm = "AM (صباحاً)" if hr < 12 else "PM (مساءً)"
            hr12 = hr if hr <= 12 else hr - 12
            if hr12 == 0: hr12 = 12
            time_desc = f"At {hr12:02d}:{mn:02d} {am_pm} (الساعة {hr:02d}:{mn:02d} بنظام 24 ساعة)"
        elif m.startswith("*/"):
            val = m.split("/")[1]
            time_desc = f"Every {val} minutes at hour {h} (كل {val} دقائق في الساعة {h})"
        else:
            time_desc = f"At hour {h}, minute {m} (في الساعة {h} والدقيقة {m})"

    if dom != "*":
        return f"{time_desc}, on day {dom} of the month (في اليوم {dom} من الشهر)"
    
    if dow == "*":
        return f"{time_desc}, Daily (بشكل يومي)"
    else:
        return f"{time_desc}, {dow_desc}"

def cron_jobs():
    jobs = []
    try:
        cron_svc_status = sh("systemctl is-active cron") == "active"
        
        for user in ["saif", "root"]:
            raw = sh(f"crontab -u {user} -l 2>/dev/null")
            for idx, line in enumerate(raw.splitlines()):
                orig_line = line
                line = line.strip()
                if not line:
                    continue
                
                is_disabled = line.startswith("#")
                if is_disabled:
                    line = line.lstrip("#").strip()
                
                parts = line.split(None, 5)
                if len(parts) >= 6:
                    sched = " ".join(parts[:5])
                    cmd = parts[5]
                else:
                    sched = "Custom"
                    cmd = line
                
                desc = "Scheduled system task (مهمة نظام مجدولة)"
                long_desc = "Executes automated system operations in the background."
                if "battery_alert.py" in cmd:
                    desc = "Battery & Power Monitor (مراقبة البطارية والطاقة)"
                    long_desc = "Checks battery level every 5 minutes. If running on battery and charge drops to 25% or below, sends an instant Telegram alert."
                elif "speedtest" in cmd:
                    desc = "Internet Speed Test (فحص سرعة الإنترنت)"
                    long_desc = "Performs periodic download, upload and ping tests to log connection performance history."
                elif "pihole" in cmd:
                    desc = "Pi-hole Maintenance & Updates (صيانة وتحديث بايهول)"
                    long_desc = "Updates ad-blocking gravity lists and database records to ensure secure and up-to-date filtering."
                elif "backup" in cmd:
                    desc = "System Backup (نسخ احتياطي للنظام)"
                    long_desc = "Creates automated backups of critical files and configurations."
                else:
                    long_desc = f"Executes command: {cmd}"

                jobs.append({
                    "id": f"{user}_{idx}",
                    "user": user,
                    "line_idx": idx,
                    "schedule": sched,
                    "schedule_desc": explain_cron_schedule(sched),
                    "command": cmd,
                    "description": desc,
                    "long_description": long_desc,
                    "active": cron_svc_status and not is_disabled,
                    "raw": orig_line
                })
    except:
        pass
    return jobs

def logged():
    return "ok" in session

def pihole_groups():
    try:
        out = sh("sudo sqlite3 /etc/pihole/gravity.db \"select id,name,enabled from 'group' order by id;\"")
        rows = []
        for line in out.splitlines():
            x = line.split("|")
            if len(x) == 3:
                rows.append({"id": x[0], "name": x[1], "enabled": x[2]})
        return rows
    except:
        return []

# --- Pi-hole real-time API (FTL keeps live data in memory; the on-disk DB only
#     flushes every DBinterval=60s, so the API is the source for live numbers) ---
_PH_SID = {"sid": None}

def _ph_auth():
    try:
        req = urllib.request.Request(
            PIHOLE_API + "/auth",
            data=json.dumps({"password": PIHOLE_PW}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=4) as r:
            _PH_SID["sid"] = json.load(r).get("session", {}).get("sid")
    except:
        _PH_SID["sid"] = None
    return _PH_SID["sid"]

def _ph_get(path):
    # reuse the cached session; re-authenticate once if it is missing/expired
    for _ in range(2):
        sid = _PH_SID["sid"] or _ph_auth()
        if not sid:
            return None
        try:
            req = urllib.request.Request(PIHOLE_API + path, headers={"sid": sid})
            with urllib.request.urlopen(req, timeout=4) as r:
                return json.load(r)
        except:
            _PH_SID["sid"] = None
    return None

def _gravity_count():
    return int(sh("sudo sqlite3 /etc/pihole/gravity.db \"SELECT count(*) FROM gravity;\"") or 0)

def pihole_stats():
    # Live home-screen numbers from the FTL API, with a DB fallback if it is down.
    try:
        j = _ph_get("/stats/summary")
        q = j["queries"]
        total = int(q["total"])
        blocked = int(q["blocked"])
        pct = round(float(q["percent_blocked"]), 1)
        domains = int(j.get("gravity", {}).get("domains_being_blocked") or 0) or _gravity_count()
        clients = int(j.get("clients", {}).get("active") or 0)
        return {"total": f"{total:,}", "blocked": f"{blocked:,}", "pct": pct,
                "domains": f"{domains:,}", "clients": clients}
    except:
        return _pihole_stats_db()

def _pihole_stats_db():
    # Fallback: read the on-disk FTL DB (up to ~60s stale). Blocked status set
    # matches Pi-hole's own definition (excludes 17=cache-stale).
    try:
        row = sh("""sudo sqlite3 /etc/pihole/pihole-FTL.db "
SELECT count(*),
 sum(CASE WHEN status IN (1,4,5,6,7,8,9,10,11,15,16,18) THEN 1 ELSE 0 END),
 count(DISTINCT client)
FROM queries WHERE timestamp >= strftime('%s','now','start of day');
" """)
        p = row.split("|")
        total = int(p[0] or 0)
        blocked = int((p[1] or "0").strip() or 0)
        clients = int(p[2] or 0)
        domains = _gravity_count()
        pct = round(blocked / total * 100, 1) if total else 0.0
        return {"total": f"{total:,}", "blocked": f"{blocked:,}", "pct": pct,
                "domains": f"{domains:,}", "clients": clients}
    except:
        return {"total": "N/A", "blocked": "N/A", "pct": 0, "domains": "N/A", "clients": "N/A"}

# Adlist IDs of the adult/porn blocklists configured in Pi-hole
ADULT_ADLISTS = "58,59,62"

def adult_attempts():
    return cached("adult", 60, _adult_attempts)

def _adult_attempts(n=8):
    # Recent attempts to reach domains on the adult blocklists (last 24h).
    try:
        out = sh(f"""sudo sqlite3 /etc/pihole/pihole-FTL.db "
ATTACH '/etc/pihole/gravity.db' AS g;
SELECT q.domain, q.client, count(*) c, max(q.timestamp) t
FROM queries q
WHERE q.timestamp >= strftime('%s','now','-1 day')
  AND q.status IN (1,4,5,6,7,8,9,10,11,15,16,18)
  AND q.domain IN (SELECT domain FROM g.gravity WHERE adlist_id IN ({ADULT_ADLISTS}))
GROUP BY q.domain, q.client ORDER BY t DESC LIMIT {n};" """)
        rows = []
        for line in out.splitlines():
            x = line.split("|")
            if len(x) == 4:
                ts = time.strftime("%m-%d %H:%M", time.localtime(int(float(x[3]))))
                rows.append({"domain": x[0], "client": x[1], "count": x[2], "time": ts})
        return rows
    except:
        return []

def top_blocked(n=5):
    return cached("topdom", 30, lambda: _top_blocked(n))

def _top_blocked(n):
    try:
        j = _ph_get(f"/stats/top_domains?blocked=true&count={n}")
        return [{"domain": d["domain"], "count": d["count"]} for d in j["domains"]]
    except:
        return []

def top_clients(n=5):
    return cached("topcli", 30, lambda: _top_clients(n))

def _top_clients(n):
    try:
        j = _ph_get(f"/stats/top_clients?count={n}")
        return [{"name": (c.get("name") or c.get("ip")), "count": c["count"]} for c in j["clients"]]
    except:
        return []

def query_counts_24h(domain_filter="", client_filter=""):
    domain_filter = re.sub(r"[^a-zA-Z0-9._:-]", "", domain_filter or "")[:100]
    client_filter = re.sub(r"[^a-zA-Z0-9._:-]", "", client_filter or "")[:100]
    key = f"query_counts_24h:{domain_filter.lower()}:{client_filter.lower()}"
    return cached(key, 30, lambda: _query_counts_24h(domain_filter, client_filter))

def _query_counts_24h(domain_filter="", client_filter=""):
    # Count every matching DNS query in the last 24 hours, not just the five
    # newest results displayed in the table.
    blocked_statuses = "1,4,5,6,7,8,9,10,11,15,16,18"
    clauses = ["timestamp >= strftime('%s','now','-1 day')"]
    if domain_filter:
        clauses.append("lower(domain) LIKE '%" + domain_filter.lower() + "%'")
    if client_filter:
        clauses.append("lower(client) LIKE '%" + client_filter.lower() + "%'")
    sql = f"""
SELECT
  sum(CASE WHEN status IN ({blocked_statuses}) THEN 1 ELSE 0 END),
  sum(CASE WHEN status IN ({blocked_statuses}) THEN 0 ELSE 1 END)
FROM queries WHERE {' AND '.join(clauses)};
"""
    try:
        result = subprocess.run(
            ["sudo", "sqlite3", "-separator", "|", "/etc/pihole/pihole-FTL.db", sql],
            capture_output=True, text=True, timeout=10, check=False)
        values = result.stdout.strip().split("|")
        return {"blocked": int(values[0] or 0), "allowed": int(values[1] or 0)}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {"blocked": 0, "allowed": 0}

def recent_queries(domain_filter="", client_filter="", n=5):
    """Return recent Pi-hole DNS queries, optionally filtered by domain/client."""
    domain_filter = re.sub(r"[^a-zA-Z0-9._:-]", "", domain_filter or "")[:100]
    client_filter = re.sub(r"[^a-zA-Z0-9._:-]", "", client_filter or "")[:100]
    if not domain_filter and not client_filter:
        return [], domain_filter, client_filter
    clauses = ["q.timestamp >= strftime('%s','now','-1 day')"]
    if domain_filter:
        clauses.append("lower(q.domain) LIKE '%" + domain_filter.lower() + "%'")
    if client_filter:
        clauses.append("lower(q.client) LIKE '%" + client_filter.lower() + "%'")
    sql = """
SELECT datetime(q.timestamp, 'unixepoch', 'localtime'), q.domain, q.client, q.status
FROM queries q WHERE %s ORDER BY q.timestamp DESC LIMIT %d;
""" % (" AND ".join(clauses), n)
    try:
        result = subprocess.run(
            ["sudo", "sqlite3", "-separator", "|", "/etc/pihole/pihole-FTL.db", sql],
            capture_output=True, text=True, timeout=10, check=False)
        blocked = {1, 4, 5, 6, 7, 8, 9, 10, 11, 15, 16, 18}
        rows = []
        for line in result.stdout.splitlines():
            values = line.split("|", 3)
            if len(values) == 4:
                status = int(values[3]) if values[3].isdigit() else -1
                rows.append({"time": values[0], "domain": values[1], "client": values[2],
                             "status": "Blocked" if status in blocked else "Allowed"})
        return rows, domain_filter, client_filter
    except (OSError, subprocess.TimeoutExpired):
        return [], domain_filter, client_filter

def speedtest():
    try:
        with open("/tmp/speedtest.txt") as f:
            x = f.read().strip().split("|")
        if len(x) >= 4:
            return {
                "down": x[0],
                "up": x[1],
                "ping": x[2],
                "time": x[3]
            }
    except:
        pass
    return {
        "down":"N/A",
        "up":"N/A",
        "ping":"N/A",
        "time":"Unavailable"
    }

def speed_history(n=4):
    # Last n speed tests (newest first) from the history log written by run_speedtest.sh
    try:
        with open("/tmp/speedtest_history.txt") as f:
            lines = [l.strip() for l in f if l.strip()]
        rows = []
        for line in reversed(lines[-n:]):
            x = line.split("|")
            if len(x) >= 4:
                rows.append({"down": x[0], "up": x[1],
                             "ping": x[2].split(".")[0], "time": x[3]})
        return rows
    except:
        return []

def updates_count():
    return cached("updates", 1800, _updates_count)

def _updates_count():
    try:
        x = sh("bash -c \"apt list --upgradable 2>/dev/null | tail -n +2 | wc -l\"")
        n = int(x.strip() or 0)
        if n <= 0:
            return "System Up To Date"
        return f"Updates Available ({n})"
    except:
        return "Update OS"

# ==================================================
# HTML - MODERN DESIGN
# ==================================================
HTML = '''
<!DOCTYPE html>
<html lang="ar" dir="ltr">
<head>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{{version}}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #060a13;
            --bg-secondary: #0f1826;
            --bg-card: rgba(18, 27, 45, 0.60);
            --bg-glass: rgba(255, 255, 255, 0.035);
            --primary: #4f8cff;
            --primary-light: #7fb0ff;
            --primary-glow: rgba(79, 140, 255, 0.40);
            --success: #10b981;
            --success-glow: rgba(16, 185, 129, 0.3);
            --danger: #ef4444;
            --danger-glow: rgba(239, 68, 68, 0.3);
            --warning: #f59e0b;
            --warning-glow: rgba(245, 158, 11, 0.3);
            --purple: #8b5cf6;
            --cyan: #22d3ee;
            --text: #f8fafc;
            --text-secondary: #a5b0c2;
            --text-muted: #6b7688;
            --border: rgba(255, 255, 255, 0.07);
            --border-light: rgba(255, 255, 255, 0.16);
            --shadow: 0 24px 50px -12px rgba(0, 0, 0, 0.6);
            --radius: 22px;
            --radius-sm: 16px;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text);
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* Animated Background */
        body::before {
            content: '';
            position: fixed;
            top: -10%;
            left: -10%;
            width: 120%;
            height: 120%;
            background:
                radial-gradient(ellipse 80% 60% at 15% 8%, rgba(79, 140, 255, 0.18) 0%, transparent 55%),
                radial-gradient(ellipse 70% 55% at 88% 18%, rgba(139, 92, 246, 0.15) 0%, transparent 55%),
                radial-gradient(ellipse 90% 70% at 50% 105%, rgba(34, 211, 238, 0.09) 0%, transparent 60%);
            pointer-events: none;
            z-index: -1;
            animation: auroraShift 20s ease-in-out infinite alternate;
        }

        @keyframes auroraShift {
            0%   { transform: translate3d(0, 0, 0) scale(1); }
            100% { transform: translate3d(0, -2.5%, 0) scale(1.08); }
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
        }

        /* Header */
        header {
            background: var(--bg-glass);
            backdrop-filter: blur(20px);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 28px 32px;
            margin-bottom: 32px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 24px;
            box-shadow: var(--shadow);
            position: relative;
            overflow: hidden;
        }

        header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, var(--primary-glow), transparent);
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .logo-icon {
            width: 56px;
            height: 56px;
            background: linear-gradient(135deg, var(--primary), var(--purple));
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 8px 32px var(--primary-glow);
        }

        .logo-icon svg {
            width: 32px;
            height: 32px;
            fill: white;
        }

        .header-info h1 {
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #fff, #e5e7eb);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .header-meta {
            display: flex;
            align-items: center;
            gap: 16px;
            margin-top: 4px;
        }

        .version-badge {
            background: var(--bg-secondary);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-secondary);
            border: 1px solid var(--border);
        }

        .uptime-text {
            font-size: 13px;
            color: var(--text-muted);
            font-weight: 500;
        }

        .status-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }

        .status-dot.online {
            background: var(--success);
            box-shadow: 0 0 12px var(--success-glow);
        }

        .status-dot.offline {
            background: var(--danger);
            box-shadow: 0 0 12px var(--danger-glow);
            animation: none;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.7; transform: scale(1.1); }
        }

        .speed-panel {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 20px 24px;
            min-width: 240px;
        }

        .speed-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }

        .speed-item {
            text-align: center;
        }

        .speed-label {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }

        .speed-value {
            font-size: 22px;
            font-weight: 800;
        }

        .speed-value.download {
            color: var(--primary-light);
        }

        .speed-value.upload {
            color: var(--success);
        }

        .speed-meta {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: var(--text-muted);
            margin-bottom: 12px;
        }

        .btn-speedtest {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 12px;
            background: linear-gradient(135deg, var(--primary), var(--purple));
            color: white;
            font-weight: 700;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .btn-speedtest:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px var(--primary-glow);
        }

        .btn-speedtest:active {
            transform: scale(0.98);
        }

        /* Section Styles */
        .section {
            margin-bottom: 32px;
        }

        .section-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 20px;
        }

        .section-icon {
            width: 40px;
            height: 40px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .section-icon.blue { background: rgba(59, 130, 246, 0.15); }
        .section-icon.green { background: rgba(16, 185, 129, 0.15); }
        .section-icon.purple { background: rgba(139, 92, 246, 0.15); }
        .section-icon.orange { background: rgba(245, 158, 11, 0.15); }

        .section-icon svg {
            width: 22px;
            height: 22px;
        }

        .section-title {
            font-size: 18px;
            font-weight: 700;
        }

        /* Services Grid */
        .services-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
        }

        @media (min-width: 768px) {
            .services-grid { grid-template-columns: repeat(3, 1fr); }
        }

        @media (min-width: 1024px) {
            .services-grid { grid-template-columns: repeat(6, 1fr); }
        }

        .service-card {
            background: var(--bg-glass);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 20px;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }

        .service-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--primary), var(--purple));
            opacity: 0;
            transition: opacity 0.3s ease;
        }

        .service-card:hover {
            border-color: var(--border-light);
            transform: translateY(-4px);
            box-shadow: var(--shadow);
        }

        .service-card:hover::before {
            opacity: 1;
        }

        /* Show Pi-hole first in the service controls grid. */
        .pihole-card { order: -1; }

        .service-icon {
            width: 48px;
            height: 48px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 14px;
        }

        .service-icon svg {
            width: 26px;
            height: 26px;
        }

        .service-icon.youtube { background: rgba(255, 0, 0, 0.15); }
        .service-icon.pihole { background: rgba(142, 92, 246, 0.15); }
        .service-icon.vpn { background: rgba(59, 130, 246, 0.15); }
        .service-icon.bot { background: rgba(16, 185, 129, 0.15); }
        .service-icon.media { background: rgba(245, 158, 11, 0.15); }
        .service-icon.mesh { background: rgba(236, 72, 153, 0.15); }

        .service-name {
            font-size: 14px;
            font-weight: 700;
            margin-bottom: 6px;
            color: var(--text);
        }

        .service-status {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 14px;
        }

        .status-badge {
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }

        .status-badge.on {
            background: rgba(16, 185, 129, 0.15);
            color: var(--success);
        }

        .status-badge.off {
            background: rgba(239, 68, 68, 0.15);
            color: var(--danger);
        }

        .service-actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        .btn-service {
            padding: 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 700;
            text-align: center;
            text-decoration: none;
            transition: all 0.2s ease;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }

        .btn-service.on {
            background: rgba(16, 185, 129, 0.1);
            color: var(--success);
            border: 1px solid rgba(16, 185, 129, 0.2);
        }

        .btn-service.off {
            background: rgba(239, 68, 68, 0.1);
            color: var(--danger);
            border: 1px solid rgba(239, 68, 68, 0.2);
        }

        .btn-service:hover {
            transform: scale(1.05);
        }

        .btn-service.on:hover {
            background: var(--success);
            color: white;
        }

        .btn-service.off:hover {
            background: var(--danger);
            color: white;
        }

        .pihole-timer {
            display: flex;
            gap: 8px;
            margin-top: 10px;
        }

        .pihole-timer input {
            min-width: 0;
            width: 72px;
            padding: 9px 8px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: var(--bg-secondary);
            color: var(--text);
            font: inherit;
            font-size: 12px;
            text-align: center;
        }

        .pihole-timer button {
            flex: 1;
            padding: 9px 8px;
            border: 1px solid rgba(245, 158, 11, 0.28);
            border-radius: 10px;
            background: rgba(245, 158, 11, 0.12);
            color: var(--warning);
            font-size: 11px;
            font-weight: 700;
            cursor: pointer;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }

        .pihole-timer button:hover {
            background: var(--warning);
            color: #1f1300;
        }

        .timer-hint {
            margin-top: 8px;
            color: var(--text-muted);
            font-size: 10px;
            line-height: 1.35;
        }

        /* Sub Groups */
        .groups-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }

        @media (min-width: 768px) {
            .groups-grid { grid-template-columns: repeat(3, 1fr); }
        }

        /* Health Cards */
        .health-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
        }

        @media (min-width: 768px) {
            .health-grid { grid-template-columns: repeat(4, 1fr); }
        }

        .health-card {
            background: var(--bg-glass);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 24px;
            position: relative;
            overflow: hidden;
        }

        .health-card::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--bar-color, var(--primary));
            opacity: 0.6;
        }

        .health-label {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }

        .health-value {
            font-size: 32px;
            font-weight: 800;
            margin-bottom: 16px;
            font-variant-numeric: tabular-nums;
        }

        .health-bar {
            height: 8px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            overflow: hidden;
        }

        .health-fill {
            height: 100%;
            border-radius: 10px;
            transition: width 0.8s ease;
        }

        .health-fill.cpu { background: linear-gradient(90deg, var(--primary), var(--primary-light)); }
        .health-fill.ram { background: linear-gradient(90deg, var(--warning), #fbbf24); }
        .health-fill.disk { background: linear-gradient(90deg, var(--danger), #f87171); }
        .health-fill.temp { background: linear-gradient(90deg, var(--success), #34d399); }

        /* Games List */
        .games-card {
            background: var(--bg-glass);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 24px;
        }

        .games-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .game-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 14px 16px;
            background: var(--bg-secondary);
            border-radius: 12px;
            border: 1px solid var(--border);
            transition: all 0.2s ease;
        }

        .game-item:hover {
            border-color: var(--border-light);
            transform: translateX(4px);
        }

        .game-domain {
            font-size: 13px;
            font-weight: 600;
            color: var(--text);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 200px;
        }

        .game-count {
            font-size: 14px;
            font-weight: 800;
            color: var(--danger);
            background: rgba(239, 68, 68, 0.1);
            padding: 4px 12px;
            border-radius: 20px;
        }

        /* DNS Query Search */
        .query-card { padding: 20px; }
        .query-form { display: grid; grid-template-columns: 1fr 1fr auto; gap: 10px; margin-bottom: 16px; }
        .query-form input {
            min-width: 0; padding: 12px 14px; border: 1px solid var(--border);
            border-radius: 10px; background: var(--bg-secondary); color: var(--text); font: inherit;
        }
        .query-form button, .query-action {
            border: 1px solid rgba(79, 140, 255, .3); border-radius: 10px; background: rgba(79, 140, 255, .15);
            color: var(--primary-light); font: inherit; font-weight: 700; cursor: pointer;
        }
        .query-form button { padding: 0 18px; }
        .query-summary { display: flex; gap: 8px; margin: 0 0 14px; }
        .query-summary span { padding: 5px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; }
        .query-summary .blocked { color: var(--danger); background: rgba(239, 68, 68, .12); }
        .query-summary .allowed { color: var(--success); background: rgba(16, 185, 129, .12); }
        .query-results { overflow-x: auto; }
        .query-table { width: 100%; border-collapse: collapse; min-width: 680px; }
        .query-table th, .query-table td { padding: 11px 10px; border-bottom: 1px solid var(--border); text-align: left; font-size: 12px; }
        .query-table th { color: var(--text-muted); font-size: 10px; text-transform: uppercase; letter-spacing: .4px; }
        .query-domain { font-weight: 700; color: var(--text); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .query-status { font-weight: 700; color: var(--success); }
        .query-status.blocked { color: var(--danger); }
        .query-actions { display: flex; gap: 6px; }
        .query-action { padding: 6px 9px; font-size: 10px; }
        .query-action.block { color: var(--danger); border-color: rgba(239, 68, 68, .3); background: rgba(239, 68, 68, .1); }
        @media (max-width: 640px) { .query-form { grid-template-columns: 1fr; } .query-form button { padding: 12px; } }

        /* System Actions */
        .actions-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }

        @media (min-width: 768px) {
            .actions-grid { grid-template-columns: repeat(4, 1fr); }
        }

        .action-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            padding: 18px;
            border-radius: var(--radius-sm);
            font-size: 13px;
            font-weight: 700;
            text-decoration: none;
            transition: all 0.3s ease;
            border: 1px solid var(--border);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .action-btn svg {
            width: 20px;
            height: 20px;
        }

        .action-btn.restart {
            background: linear-gradient(135deg, var(--primary), var(--purple));
            color: white;
        }

        .action-btn.reboot {
            background: linear-gradient(135deg, var(--danger), #dc2626);
            color: white;
        }

        .action-btn.update {
            background: linear-gradient(135deg, var(--success), #059669);
            color: white;
        }

        .action-btn.pihole {
            background: linear-gradient(135deg, #f60d1a, #b91c1c);
            color: white;
        }

        .action-btn.rollback {
            background: var(--bg-secondary);
            color: var(--text);
            border-color: var(--border);
        }

        .action-btn.logout {
            background: var(--bg-secondary);
            color: var(--text-muted);
            border-color: var(--border);
        }

        .action-btn:hover {
            transform: translateY(-3px);
            box-shadow: var(--shadow);
        }

        .action-btn:active {
            transform: scale(0.98);
        }

        /* Footer */
        .footer {
            text-align: center;
            padding: 32px;
            color: var(--text-muted);
            font-size: 13px;
            font-weight: 500;
            border-top: 1px solid var(--border);
            margin-top: 48px;
        }

        .footer span {
            color: var(--success);
            font-weight: 700;
        }

        .footer span.offline {
            color: var(--danger);
        }

        /* Toast */
        .toast {
            position: fixed;
            top: 24px;
            left: 50%;
            transform: translateX(-50%) translateY(-100px);
            background: linear-gradient(135deg, var(--bg-secondary), var(--bg-primary));
            color: var(--text);
            padding: 16px 28px;
            border-radius: 16px;
            border: 1px solid var(--border);
            z-index: 9999;
            font-size: 14px;
            font-weight: 700;
            box-shadow: var(--shadow);
            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .toast.show {
            transform: translateX(-50%) translateY(0);
        }

        .toast svg {
            width: 20px;
            height: 20px;
            fill: var(--success);
        }

        /* Sub Section Card */
        .card {
            background: var(--bg-glass);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 24px;
            margin-top: 16px;
        }

        /* Mobile Optimizations */
        @media (max-width: 640px) {
            .container {
                padding: 16px;
            }

            header {
                padding: 20px;
                flex-direction: column;
                align-items: stretch;
            }

            .header-left {
                justify-content: center;
            }

            .header-info {
                text-align: center;
            }

            .header-meta {
                justify-content: center;
                flex-wrap: wrap;
            }

            .speed-panel {
                min-width: 100%;
            }

            .health-value {
                font-size: 26px;
            }

            .action-btn {
                padding: 14px;
                font-size: 11px;
            }
        }

        /* ===================== v14 design refresh ===================== */
        @keyframes fadeUp {
            from { opacity: 0; transform: translateY(18px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        header, .section { animation: fadeUp .55s cubic-bezier(.2,.7,.2,1) both; }
        .section:nth-of-type(1) { animation-delay: .05s; }
        .section:nth-of-type(2) { animation-delay: .11s; }
        .section:nth-of-type(3) { animation-delay: .17s; }
        .section:nth-of-type(4) { animation-delay: .23s; }
        .section:nth-of-type(5) { animation-delay: .29s; }

        /* refined glass + subtle top sheen */
        header, .service-card, .health-card, .games-card, .card {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0) 60%),
                var(--bg-card);
            backdrop-filter: blur(22px) saturate(125%);
            -webkit-backdrop-filter: blur(22px) saturate(125%);
        }

        /* auto-refresh countdown bar (top of page) */
        #refreshbar {
            position: fixed; top: 0; left: 0; height: 3px; width: 0%;
            background: linear-gradient(90deg, var(--primary), var(--purple), var(--cyan));
            box-shadow: 0 0 14px var(--primary-glow);
            z-index: 10000; border-radius: 0 3px 3px 0;
            animation: refill 10s linear infinite;
        }
        @keyframes refill { from { width: 0; } to { width: 100%; } }

        /* live clock */
        .clock {
            font-variant-numeric: tabular-nums;
            font-size: 15px; font-weight: 800; color: var(--text);
            letter-spacing: .5px;
            padding: 4px 12px; border-radius: 20px;
            background: rgba(255,255,255,0.04); border: 1px solid var(--border);
        }

        /* health value takes its metric color + smoother hover */
        .health-value { color: var(--bar-color, var(--text)); }
        .health-card { transition: transform .3s ease, border-color .3s ease, box-shadow .3s ease; }
        .health-card:hover { transform: translateY(-4px); border-color: var(--border-light); box-shadow: var(--shadow); }

        /* logo glow pulse */
        .logo-icon { animation: logoGlow 4s ease-in-out infinite; }
        @keyframes logoGlow {
            0%,100% { box-shadow: 0 8px 32px var(--primary-glow); }
            50%     { box-shadow: 0 8px 44px var(--primary-glow), 0 0 22px rgba(139,92,246,0.35); }
        }

        /* refined scrollbar */
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.09); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.18); }

        /* speed test history table */
        .sthist { width: 100%; border-collapse: collapse; }
        .sthist th {
            text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 700;
            text-transform: uppercase; letter-spacing: .5px; color: var(--text-muted);
            border-bottom: 1px solid var(--border);
        }
        .sthist td {
            padding: 14px; font-size: 14px; font-weight: 700;
            border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums;
        }
        .sthist tr:last-child td { border-bottom: none; }
        .sthist tbody tr { transition: background .2s ease; }
        .sthist tbody tr:hover { background: rgba(255,255,255,0.03); }
        .sthist .t  { color: var(--text-secondary); font-weight: 600; }
        .sthist .dl { color: var(--primary-light); }
        .sthist .ul { color: var(--success); }
        .sthist .pg { color: var(--text-secondary); }
        .sthist small { color: var(--text-muted); font-weight: 500; font-size: 11px; }
        @media (max-width: 640px) {
            .sthist th, .sthist td { padding: 10px 8px; font-size: 12px; }
        }

        /* top lists (two columns) */
        .toplists-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
        @media (min-width: 768px) { .toplists-grid { grid-template-columns: 1fr 1fr; } }
        .toplist-title {
            font-size: 12px; font-weight: 700; color: var(--text-secondary);
            text-transform: uppercase; letter-spacing: .5px; margin-bottom: 14px;
        }

        @media (prefers-reduced-motion: reduce) {
            *, body::before { animation: none !important; }
        }
    </style>
</head>
<body>
    <div id="refreshbar"></div>
    <div class="container">
        <!-- Header -->
        <header>
            <div class="header-left">
                <div class="logo-icon">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>
                    </svg>
                </div>
                <div class="header-info">
                    <h1>Home Server</h1>
                    <div class="header-meta">
                        <span class="clock" id="clock">--:--:--</span>
                        <span class="version-badge">{{version}}</span>
                        <span class="uptime-text" id="hdr_uptime">up {{uptime}}</span>
                        <div class="status-indicator" id="hdr_status">
                            <div class="status-dot {{'online' if net else 'offline'}}"></div>
                            <span>{{'Online' if net else 'Offline'}}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="speed-panel">
                <div class="speed-grid">
                    <div class="speed-item">
                        <div class="speed-label">Download</div>
                        <div class="speed-value download" id="sp_down">{{ spd.down if spd is defined else 'N/A' }} <small style="font-size:12px;font-weight:500;">Mbps</small></div>
                    </div>
                    <div class="speed-item">
                        <div class="speed-label">Upload</div>
                        <div class="speed-value upload" id="sp_up">{{ spd.up if spd is defined else 'N/A' }} <small style="font-size:12px;font-weight:500;">Mbps</small></div>
                    </div>
                </div>
                <div class="speed-meta" id="sp_meta">
                    <span>Ping {{ spd.ping if spd is defined else 'N/A' }} ms</span>
                    <span>{{ spd.time if spd is defined else 'Unavailable' }}</span>
                </div>
                <button class="btn-speedtest" onclick="fetch('/action/manual_speedtest');showToast('Running Speed Test… result in ~40s')">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.56 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.44 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
                    </svg>
                    Run Speed Test
                </button>
            </div>
        </header>

        <!-- Live Bandwidth -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon green">
                    <svg viewBox="0 0 24 24" fill="#10b981">
                        <path d="M3 17h2v-6H3v6zm4 0h2V7H7v10zm4 0h2v-8h-2v8zm4 0h2V5h-2v12zm4 0h2v-4h-2v4z"/>
                    </svg>
                </div>
                <h2 class="section-title">Live Bandwidth <span id="bw_iface" style="font-size:12px;color:var(--text-muted);font-weight:600;"></span></h2>
            </div>

            <div class="health-grid" style="grid-template-columns:1fr 1fr;">
                <div class="health-card" style="--bar-color: var(--primary);">
                    <div class="health-label">&#8595; Download</div>
                    <div class="health-value" id="bw_down" style="color:var(--primary-light);">&#8226;&#8226;&#8226;</div>
                    <canvas id="bw_down_spark" width="320" height="46" style="width:100%;height:46px;display:block;margin-top:8px;"></canvas>
                </div>
                <div class="health-card" style="--bar-color: var(--success);">
                    <div class="health-label">&#8593; Upload</div>
                    <div class="health-value" id="bw_up" style="color:var(--success);">&#8226;&#8226;&#8226;</div>
                    <canvas id="bw_up_spark" width="320" height="46" style="width:100%;height:46px;display:block;margin-top:8px;"></canvas>
                </div>
            </div>
        </section>

        <!-- Service Controls -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon blue">
                    <svg viewBox="0 0 24 24" fill="var(--primary)">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                    </svg>
                </div>
                <h2 class="section-title">Service Controls</h2>
            </div>

            <div class="services-grid">
                <!-- YouTube Block -->
                <div class="service-card">
                    <div class="service-icon youtube">
                        <svg viewBox="0 0 24 24" fill="#ef4444">
                            <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
                        </svg>
                    </div>
                    <div class="service-name">YouTube Block</div>
                    <div class="service-status">
                        <span class="status-badge {{'on' if yt=='Enabled' else 'off'}}" id="st_yt">{{yt}}</span>
                    </div>
                    <div class="service-actions">
                        <a href="/action/youtube_on" class="btn-service on">Enable</a>
                        <a href="/action/youtube_off" class="btn-service off">Disable</a>
                    </div>
                </div>

                <!-- Pi-hole -->
                <div class="service-card pihole-card">
                    <div class="service-icon pihole">
                        <svg viewBox="0 0 24 24" fill="#8b5cf6">
                            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                        </svg>
                    </div>
                    <div class="service-name">Pi-hole Adblock</div>
                    <div class="service-status">
                        <span class="status-badge {{'on' if ph=='Enabled' else 'off'}}" id="st_ph">{{ph}}</span>
                    </div>
                    <div class="service-actions">
                        <a href="/action/pihole_on" class="btn-service on">Enable</a>
                        <a href="/action/pihole_off" class="btn-service off">Disable</a>
                    </div>
                    <form class="pihole-timer" action="/pihole/pause" method="post">
                        <input type="number" name="minutes" min="1" max="1440" value="5" required aria-label="Minutes to pause Pi-hole">
                        <button type="submit">Disable for time</button>
                    </form>
                    {% if pause %}
                    <div class="timer-hint" id="pihole_timer_status" data-pause-until="{{pause.ends_at}}">
                        Blocking re-enables in <strong>--:--</strong>
                    </div>
                    {% else %}
                    <div class="timer-hint" id="pihole_timer_status">Disables blocking, then enables it automatically after the chosen minutes.</div>
                    {% endif %}
                </div>

                <!-- VPN -->
                <div class="service-card">
                    <div class="service-icon vpn">
                        <svg viewBox="0 0 24 24" fill="#3b82f6">
                            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
                        </svg>
                    </div>
                    <div class="service-name">Proton VPN</div>
                    <div class="service-status">
                        <span class="status-badge {{'on' if vpn=='active' else 'off'}}" id="st_vpn">{{vpn}}</span>
                    </div>
                    <div class="service-actions">
                        <a href="/action/vpn_on" class="btn-service on">Start</a>
                        <a href="/action/vpn_off" class="btn-service off">Stop</a>
                    </div>
                </div>

                <!-- Telegram Bot -->
                <div class="service-card">
                    <div class="service-icon bot">
                        <svg viewBox="0 0 24 24" fill="#10b981">
                            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69.01-.03.01-.14-.07-.2-.08-.06-.19-.04-.27-.02-.12.03-1.99 1.27-5.61 3.73-.53.36-1.01.53-1.45.52-.48-.01-1.4-.27-2.08-.49-.83-.27-1.49-.42-1.43-.88.03-.24.37-.49 1.02-.74 3.78-1.45 6.29-2.42 7.48-3.01 3.65-1.79 4.41-2.11 4.93-2.15.13-.01.42.04.56.27.12.2.13.46.08.58-.04.12-.06.19-.07.28z"/>
                        </svg>
                    </div>
                    <div class="service-name">Telegram Bot</div>
                    <div class="service-status">
                        <span class="status-badge {{'on' if bot=='active' else 'off'}}" id="st_bot">{{bot}}</span>
                    </div>
                    <div class="service-actions">
                        <a href="/action/tg_on" class="btn-service on">Start</a>
                        <a href="/action/tg_off" class="btn-service off">Stop</a>
                    </div>
                </div>

                <!-- Jellyfin -->
                <div class="service-card">
                    <div class="service-icon media">
                        <svg viewBox="0 0 24 24" fill="#f59e0b">
                            <path d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z"/>
                        </svg>
                    </div>
                    <div class="service-name">Media Server</div>
                    <div class="service-status">
                        <span class="status-badge {{'on' if jelly=='active' else 'off'}}" id="st_jelly">{{jelly}}</span>
                    </div>
                    <div class="service-actions">
                        <a href="/action/jellyfin_on" class="btn-service on">Start</a>
                        <a href="/action/jellyfin_off" class="btn-service off">Stop</a>
                    </div>
                </div>

                <!-- Tailscale -->
                <div class="service-card">
                    <div class="service-icon mesh">
                        <svg viewBox="0 0 24 24" fill="#ec4899">
                            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
                        </svg>
                    </div>
                    <div class="service-name">Tailscale Mesh</div>
                    <div class="service-status">
                        <span class="status-badge {{'on' if tailscale=='active' else 'off'}}" id="st_ts">{{tailscale}}</span>
                    </div>
                    <div class="service-actions">
                        <a href="/action/tailscale_on" class="btn-service on">Start</a>
                        <a href="/action/tailscale_off" class="btn-service off">Stop</a>
                    </div>
                </div>
            </div>
        </section>

        <!-- Pi-hole Statistics -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon purple">
                    <svg viewBox="0 0 24 24" fill="#8b5cf6">
                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                    </svg>
                </div>
                <h2 class="section-title">Pi-hole Statistics</h2>
            </div>

            <div class="health-grid" id="ph_grid">
                <div class="health-card" style="--bar-color: var(--primary);">
                    <div class="health-label">Total Queries (Today)</div>
                    <div class="health-value" style="font-size:28px;">{{ phstats.total if phstats is defined else 'N/A' }}</div>
                </div>
                <div class="health-card" style="--bar-color: var(--danger);">
                    <div class="health-label">Queries Blocked</div>
                    <div class="health-value" style="font-size:28px;">{{ phstats.blocked if phstats is defined else 'N/A' }}</div>
                </div>
                <div class="health-card" style="--bar-color: var(--success);">
                    <div class="health-label">Percent Blocked</div>
                    <div class="health-value">{{ phstats.pct if phstats is defined else 0 }}%</div>
                    <div class="health-bar">
                        <div class="health-fill temp" style="width: {{ phstats.pct if phstats is defined else 0 }}%;"></div>
                    </div>
                </div>
                <div class="health-card" style="--bar-color: var(--warning);">
                    <div class="health-label">Domains on Blocklist</div>
                    <div class="health-value" style="font-size:28px;">{{ phstats.domains if phstats is defined else 'N/A' }}</div>
                </div>
            </div>
        </section>

        <!-- Pi-hole Top Lists -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon purple">
                    <svg viewBox="0 0 24 24" fill="#8b5cf6">
                        <path d="M3 9h2V7H3v2zm0 4h2v-2H3v2zm0 4h2v-2H3v2zm4 0h14v-2H7v2zm0-4h14v-2H7v2zm0-6v2h14V7H7z"/>
                    </svg>
                </div>
                <h2 class="section-title">Pi-hole Top Lists (Today)</h2>
            </div>

            <div class="toplists-grid">
                <div class="games-card">
                    <div class="toplist-title">Top Blocked Domains</div>
                    <div class="games-list" id="topdom_list">
                        {% for d in topdom %}
                        <div class="game-item">
                            <span class="game-domain">{{d.domain}}</span>
                            <span class="game-count">{{d.count}}</span>
                        </div>
                        {% endfor %}
                        {% if not topdom %}
                        <div class="game-item"><span class="game-domain">No data</span></div>
                        {% endif %}
                    </div>
                </div>
                <div class="games-card">
                    <div class="toplist-title">Top Clients</div>
                    <div class="games-list" id="topcli_list">
                        {% for c in topcli %}
                        <div class="game-item">
                            <span class="game-domain">{{c.name}}</span>
                            <span class="game-count" style="color:var(--primary-light);background:rgba(79,140,255,0.12);">{{c.count}}</span>
                        </div>
                        {% endfor %}
                        {% if not topcli %}
                        <div class="game-item"><span class="game-domain">No data</span></div>
                        {% endif %}
                    </div>
                </div>
            </div>
        </section>

        <!-- Recent DNS Query Search -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon blue">
                    <svg viewBox="0 0 24 24" fill="var(--primary)">
                        <path d="M9.5 3a6.5 6.5 0 104.1 11.54l4.43 4.43 1.41-1.41-4.43-4.43A6.5 6.5 0 009.5 3zm0 2a4.5 4.5 0 110 9 4.5 4.5 0 010-9z"/>
                    </svg>
                </div>
                <h2 class="section-title">Recent DNS Query Search</h2>
            </div>
            <div class="games-card query-card" id="query_search">
                <form class="query-form" id="query_form" action="/dashboard" method="get">
                    <input name="domain" value="{{query_domain}}" placeholder="Search domain, e.g. youtube">
                    <input name="client" value="{{query_client}}" placeholder="Search device / IP">
                    <button type="submit">Search</button>
                </form>
                <div class="query-summary">
                    <span class="blocked" id="query_blocked">Blocked{% if query_domain or query_client %}, matching search{% endif %} (24h): {{query_summary.blocked}}</span>
                    <span class="allowed" id="query_allowed">Not blocked{% if query_domain or query_client %}, matching search{% endif %} (24h): {{query_summary.allowed}}</span>
                </div>
                <div class="query-results">
                    <table class="query-table">
                        <thead><tr><th>Time</th><th>Domain</th><th>Device</th><th>Status</th><th>List action</th></tr></thead>
                        <tbody id="query_rows">
                            {% for q in queries %}
                            <tr>
                                <td>{{q.time}}</td>
                                <td class="query-domain" title="{{q.domain}}">{{q.domain}}</td>
                                <td>{{q.client}}</td>
                                <td class="query-status {{'blocked' if q.status=='Blocked' else ''}}">{{q.status}}</td>
                                <td>
                                    <div class="query-actions">
                                        <form data-query-action action="/queries/domain/allow" method="post"><input type="hidden" name="domain" value="{{q.domain}}"><button class="query-action" type="submit">Allow</button></form>
                                        <form data-query-action action="/queries/domain/block" method="post"><input type="hidden" name="domain" value="{{q.domain}}"><button class="query-action block" type="submit">Block</button></form>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                            {% if not queries %}
                            <tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:22px;">{% if query_domain or query_client %}No recent queries found.{% else %}Search a domain or device to see its five most recent queries.{% endif %}</td></tr>
                            {% endif %}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- Sub Control -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon purple">
                    <svg viewBox="0 0 24 24" fill="#8b5cf6">
                        <path d="M4 8h4V4H4v4zm6 12h4v-4h-4v4zm-6 0h4v-4H4v4zm0-6h4v-4H4v4zm6 0h4v-4h-4v4zm6-10v4h4V4h-4zm-6 4h4V4h-4v4zm6 6h4v-4h-4v4zm0 6h4v-4h-4v4z"/>
                    </svg>
                </div>
                <h2 class="section-title">Sub Control Groups</h2>
            </div>

            <div class="card">
                <div class="groups-grid" id="groups_grid">
                    {% for g in groups %}
                    <div class="service-card" style="padding: 16px;">
                        <div class="service-name">{{g.name}}</div>
                        <div class="service-status">
                            <span class="status-badge {{'off' if g.enabled=='1' else 'on'}}">
                                {{'Blocked' if g.enabled=='1' else 'Active'}}
                            </span>
                        </div>
                        <div class="service-actions">
                            <a href="/action/group_on/{{g.id}}" class="btn-service on">ON</a>
                            <a href="/action/group_off/{{g.id}}" class="btn-service off">OFF</a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </section>

        <!-- Recent Speed Tests -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon blue">
                    <svg viewBox="0 0 24 24" fill="var(--primary)">
                        <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.56 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.44 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
                    </svg>
                </div>
                <h2 class="section-title">Recent Speed Tests</h2>
            </div>

            <div class="games-card" id="speedhist">
                <table class="sthist">
                    <thead>
                        <tr><th>Time</th><th>Download</th><th>Upload</th><th>Ping</th></tr>
                    </thead>
                    <tbody>
                        {% for h in spdhist %}
                        <tr>
                            <td class="t">{{h.time}}</td>
                            <td class="dl">{{h.down}} <small>Mbps</small></td>
                            <td class="ul">{{h.up}} <small>Mbps</small></td>
                            <td class="pg">{{h.ping}} <small>ms</small></td>
                        </tr>
                        {% endfor %}
                        {% if not spdhist %}
                        <tr><td colspan="4" style="text-align:center;color:var(--text-muted);">No history yet — run a speed test</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </section>

        <!-- Resources Health -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon green">
                    <svg viewBox="0 0 24 24" fill="#10b981">
                        <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"/>
                    </svg>
                </div>
                <h2 class="section-title">Resources Health</h2>
            </div>

            <div class="health-grid" id="res_grid">
                <div class="health-card" style="--bar-color: var(--primary);">
                    <div class="health-label">CPU Usage</div>
                    <div class="health-value">{{cpu}}%</div>
                    <div class="health-bar">
                        <div class="health-fill cpu" style="width: {{cpu}}%;"></div>
                    </div>
                </div>

                <div class="health-card" style="--bar-color: var(--warning);">
                    <div class="health-label">RAM Usage</div>
                    <div class="health-value">{{ram}}%</div>
                    <div class="health-bar">
                        <div class="health-fill ram" style="width: {{ram}}%;"></div>
                    </div>
                </div>

                <div class="health-card" style="--bar-color: var(--danger);">
                    <div class="health-label">Disk Space</div>
                    <div class="health-value">{{disk}}%</div>
                    <div class="health-bar">
                        <div class="health-fill disk" style="width: {{disk}}%;"></div>
                    </div>
                </div>

                <div class="health-card" style="--bar-color: var(--success);">
                    <div class="health-label">Temperature</div>
                    <div class="health-value">{{temp}}°C</div>
                    <div class="health-bar">
                        <div class="health-fill temp" style="width: {{ (temp/80)*100 }}%;"></div>
                    </div>
                </div>

                <div class="health-card" style="--bar-color: {{ 'var(--success)' if bat.charging else ('var(--warning)' if bat.percent > 20 else 'var(--danger)') }};">
                    <div class="health-label">Power & Battery</div>
                    <div class="health-value" style="font-size: 24px;">{{bat.status}}</div>
                    <div class="health-bar">
                        <div class="health-fill" style="width: {{bat.percent}}%; background: {{ 'var(--success)' if bat.charging else ('var(--warning)' if bat.percent > 20 else 'var(--danger)') }};"></div>
                    </div>
                </div>
            </div>
        </section>

        <!-- Cron Jobs Section -->
        <section class="section">
            <div class="section-header" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div class="section-icon purple">
                        <svg viewBox="0 0 24 24" fill="#8b5cf6">
                            <path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/>
                        </svg>
                    </div>
                    <h2 class="section-title" style="margin:0;">Scheduled Cron Jobs & Management</h2>
                </div>
                <!-- Status Filter Buttons -->
                <div style="display:flex; gap:6px;">
                    <button onclick="filterCron('all')" id="btn_cron_all" class="query-action" style="padding:6px 12px; font-size:11px; background:var(--primary); color:white; border-color:var(--primary);">All</button>
                    <button onclick="filterCron('active')" id="btn_cron_active" class="query-action" style="padding:6px 12px; font-size:11px;">Active</button>
                    <button onclick="filterCron('inactive')" id="btn_cron_inactive" class="query-action" style="padding:6px 12px; font-size:11px;">Inactive</button>
                </div>
            </div>

            <!-- Cron Schedule Guide Box -->
            <div style="background:var(--bg-secondary); border:1px solid var(--border); border-radius:12px; padding:16px; margin-top:16px; margin-bottom:16px; font-size:12px; color:var(--text-secondary);">
                <strong style="color:var(--text); display:block; margin-bottom:6px;">📖 Cron Syntax Meaning (معنى رموز التوقيت):</strong>
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:8px;">
                    <div><code>*/5 * * * *</code>: Every 5 minutes (كل 5 دقائق)</div>
                    <div><code>*/10 * * * *</code>: Every 10 minutes (كل 10 دقائق)</div>
                    <div><code>0 * * * *</code>: Every hour (كل ساعة تماماً)</div>
                    <div><code>0 0 * * *</code>: Every day at midnight (يومياً 12 منتصف الليل)</div>
                </div>
            </div>

            <div class="games-card">
                <!-- Scrollable container showing up to latest 5 jobs -->
                <div style="max-height: 380px; overflow-y: auto;">
                    <table class="sthist">
                        <thead>
                            <tr>
                                <th>User</th>
                                <th>Schedule & Meaning</th>
                                <th>Task Description</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="cron_table_body">
                            {% for j in cronjobs %}
                            <tr class="cron-row" data-active="{{ 'true' if j.active else 'false' }}">
                                <td class="t" style="font-weight:700;color:var(--primary-light);">{{j.user}}</td>
                                <td>
                                    <code style="background:rgba(255,255,255,0.06);padding:3px 6px;border-radius:6px;font-size:12px;display:inline-block;margin-bottom:4px;">{{j.schedule}}</code>
                                    <div style="font-size:11px;color:var(--text-muted);">{{j.schedule_desc}}</div>
                                </td>
                                <td>
                                    <div style="color:var(--text);font-weight:600;margin-bottom:2px;">{{j.description}}</div>
                                    <div style="font-size:11px;color:var(--text-secondary);margin-bottom:4px;line-height:1.4;">{{j.long_description}}</div>
                                    <div class="t" style="font-size:11px;color:var(--text-muted);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{{j.command}}">Command: {{j.command}}</div>
                                </td>
                                <td>
                                    <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                                        <a href="/action/cron_toggle/{{j.user}}/{{j.line_idx}}" onclick="saveScroll()" class="btn-service {{'on' if j.active else 'off'}}" style="padding:6px 12px; font-size:11px;">
                                            {{ 'Disable' if j.active else 'Enable' }}
                                        </a>
                                        <button type="button" onclick="openCronEdit('{{j.user}}', '{{j.line_idx}}', '{{j.schedule}}')" class="btn-service" style="background:rgba(59,130,246,0.1); color:#3b82f6; border:1px solid rgba(59,130,246,0.2); padding:6px 12px; font-size:11px; cursor:pointer;">
                                            Edit Time
                                        </button>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                            {% if not cronjobs %}
                            <tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:20px;">No scheduled cron jobs found.</td></tr>
                            {% endif %}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- Edit Cron Modal with Preset Selector -->
        <div id="cronModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:9999; align-items:center; justify-content:center;">
            <div style="background:var(--bg); border:1px solid var(--border); border-radius:16px; padding:24px; width:90%; max-width:480px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.5);">
                <h3 style="margin-top:0; margin-bottom:12px; color:var(--text);">Edit Cron Schedule (تعديل توقيت المهمة)</h3>
                <p style="font-size:12px; color:var(--text-secondary); margin-bottom:16px;">اختر توقيت جاهز أو اكتب صيغة Cron مخصصة (مثال: <code>*/5 * * * *</code> تعني التنفيذ كل 5 دقائق).</p>
                <form method="POST" action="/action/cron_edit" onsubmit="saveScroll()">
                    <input type="hidden" name="user" id="edit_user">
                    <input type="hidden" name="line_idx" id="edit_line_idx">
                    
                    <div style="margin-bottom:14px;">
                        <label style="display:block; font-size:12px; color:var(--text-muted); margin-bottom:6px;">Quick Presets (توقيتات جاهزة):</label>
                        <select id="cron_preset" onchange="applyCronPreset(this.value)" style="width:100%; padding:10px 12px; border:1px solid var(--border); border-radius:8px; background:var(--bg-secondary); color:var(--text); font:inherit; margin-bottom:10px;">
                            <option value="">-- Custom Schedule --</option>
                            <option value="*/5 * * * *">Every 5 minutes (كل 5 دقائق)</option>
                            <option value="*/10 * * * *">Every 10 minutes (كل 10 دقائق)</option>
                            <option value="0 * * * *">Every hour (كل ساعة)</option>
                            <option value="0 0 * * *">Every day at midnight (يومياً منتصف الليل)</option>
                        </select>
                    </div>

                    <div style="margin-bottom:20px;">
                        <label style="display:block; font-size:12px; color:var(--text-muted); margin-bottom:6px;">Cron Schedule Expression:</label>
                        <input type="text" name="schedule" id="edit_schedule" required style="width:100%; padding:10px 12px; border:1px solid var(--border); border-radius:8px; background:var(--bg-secondary); color:var(--text); font:inherit; font-family:monospace;">
                    </div>
                    <div style="display:flex; justify-content:flex-end; gap:10px;">
                        <button type="button" onclick="closeCronEdit()" style="padding:8px 16px; border-radius:8px; border:1px solid var(--border); background:transparent; color:var(--text); cursor:pointer; font:inherit;">Cancel</button>
                        <button type="submit" style="padding:8px 16px; border-radius:8px; border:none; background:var(--primary); color:white; cursor:pointer; font:inherit; font-weight:700;">Save Schedule</button>
                    </div>
                </form>
            </div>
        </div>

        <script>
            function saveScroll() {
                sessionStorage.setItem('scrollpos', window.scrollY);
            }
            document.addEventListener("DOMContentLoaded", function() {
                const scrollpos = sessionStorage.getItem('scrollpos');
                if (scrollpos) {
                    window.scrollTo(0, parseInt(scrollpos));
                    sessionStorage.removeItem('scrollpos');
                }
            });

            function openCronEdit(user, lineIdx, sched) {
                document.getElementById('edit_user').value = user;
                document.getElementById('edit_line_idx').value = lineIdx;
                document.getElementById('edit_schedule').value = sched;
                document.getElementById('cron_preset').value = "";
                document.getElementById('cronModal').style.display = 'flex';
            }
            function closeCronEdit() {
                document.getElementById('cronModal').style.display = 'none';
            }
            function applyCronPreset(val) {
                if(val) {
                    document.getElementById('edit_schedule').value = val;
                }
            }
            function filterCron(status) {
                const rows = document.querySelectorAll('.cron-row');
                ['all', 'active', 'inactive'].forEach(s => {
                    const btn = document.getElementById('btn_cron_' + s);
                    if(btn) {
                        btn.style.background = s === status ? 'var(--primary)' : 'transparent';
                        btn.style.color = s === status ? 'white' : 'var(--text-secondary)';
                        btn.style.borderColor = s === status ? 'var(--primary)' : 'var(--border)';
                    }
                });
                rows.forEach(r => {
                    const active = r.dataset.active === 'true';
                    if(status === 'all') r.style.display = '';
                    else if(status === 'active') r.style.display = active ? '' : 'none';
                    else if(status === 'inactive') r.style.display = !active ? '' : 'none';
                });
            }
        </script>

        <!-- Edit Cron Modal / Form Container -->
        <div id="cronModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:9999; align-items:center; justify-content:center;">
            <div style="background:var(--bg); border:1px solid var(--border); border-radius:16px; padding:24px; width:90%; max-width:450px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.5);">
                <h3 style="margin-top:0; margin-bottom:16px; color:var(--text);">Edit Cron Schedule</h3>
                <form method="POST" action="/action/cron_edit">
                    <input type="hidden" name="user" id="edit_user">
                    <input type="hidden" name="line_idx" id="edit_line_idx">
                    <div style="margin-bottom:16px;">
                        <label style="display:block; font-size:12px; color:var(--text-muted); margin-bottom:6px;">Cron Schedule Expression (e.g. */5 * * * *)</label>
                        <input type="text" name="schedule" id="edit_schedule" required style="width:100%; padding:10px 12px; border:1px solid var(--border); border-radius:8px; background:var(--bg-secondary); color:var(--text); font:inherit;">
                    </div>
                    <div style="display:flex; justify-content:flex-end; gap:10px;">
                        <button type="button" onclick="closeCronEdit()" style="padding:8px 16px; border-radius:8px; border:1px solid var(--border); background:transparent; color:var(--text); cursor:pointer; font:inherit;">Cancel</button>
                        <button type="submit" style="padding:8px 16px; border-radius:8px; border:none; background:var(--primary); color:white; cursor:pointer; font:inherit; font-weight:700;">Save Schedule</button>
                    </div>
                </form>
            </div>
        </div>

        <script>
            function openCronEdit(user, lineIdx, sched) {
                document.getElementById('edit_user').value = user;
                document.getElementById('edit_line_idx').value = lineIdx;
                document.getElementById('edit_schedule').value = sched;
                document.getElementById('cronModal').style.display = 'flex';
            }
            function closeCronEdit() {
                document.getElementById('cronModal').style.display = 'none';
            }
        </script>

        <!-- System Actions -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon blue">
                    <svg viewBox="0 0 24 24" fill="#3b82f6">
                        <path d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>
                    </svg>
                </div>
                <h2 class="section-title">System Actions</h2>
            </div>

            <div class="actions-grid">
                <a href="/action/restart_all" class="action-btn restart">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
                    </svg>
                    Restart All
                </a>
                <a href="/action/reboot" class="action-btn reboot" onclick="return confirm('Reboot server?')">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93s3.05-7.44 7-7.93v15.86zm2-15.86c1.03.52 2 1.34 2.76 2.39H17V5.08l-2.35 1.55c-1.55-1.01-3.4-1.56-5.32-1.56C7.79 5.07 5 7.86 5 11.4s2.79 6.33 6.33 6.33c1.92 0 3.77-.55 5.32-1.56l2.35 1.55v-2.05c-.76 1.05-1.73 1.87-2.76 2.39v.01z"/>
                    </svg>
                    Reboot OS
                </a>
                <a href="#" class="action-btn update" onclick="fetch('/action/update_system');showToast('System update started… running in background');return false">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.56 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.44 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
                    </svg>
                    <span id="upd_label">{{upd}}</span>
                </a>
                <a href="#" class="action-btn pihole" onclick="fetch('/action/pihole_update');showToast('Updating Pi-hole… running in background');return false">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.56 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.44 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
                    </svg>
                    Update Pi-hole
                </a>
                <a href="/action/rollback" class="action-btn rollback">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z"/>
                    </svg>
                    Rollback
                </a>
                <a href="/logout" class="action-btn logout">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M10.09 15.59L11.5 17l5-5-5-5-1.41 1.41L12.67 11H3v2h9.67l-2.58 2.59zM19 3H5c-1.11 0-2 .9-2 2v4h2V5h14v14H5v-4H3v4c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/>
                    </svg>
                    Logout Admin
                </a>
            </div>
        </section>

        <!-- Adult Site Attempts -->
        <section class="section">
            <div class="section-header">
                <div class="section-icon" style="background:rgba(239,68,68,0.15);">
                    <svg viewBox="0 0 24 24" fill="#ef4444">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/>
                    </svg>
                </div>
                <h2 class="section-title">Adult Site Attempts (24h)</h2>
            </div>

            <div class="games-card" id="adult_list">
                {% if adult %}
                <div class="games-list">
                    {% for a in adult %}
                    <div class="game-item">
                        <div style="display:flex;flex-direction:column;gap:3px;overflow:hidden;">
                            <span class="game-domain" style="color:var(--danger);max-width:100%;">{{a.domain}}</span>
                            <span style="font-size:11px;color:var(--text-muted);">{{a.client}} • {{a.time}}</span>
                        </div>
                        <span class="game-count">{{a.count}}x</span>
                    </div>
                    {% endfor %}
                </div>
                {% else %}
                <div style="text-align:center;padding:18px;color:var(--success);font-weight:700;">✓ No adult-site attempts in the last 24 hours</div>
                {% endif %}
            </div>
        </section>

        <!-- Footer -->
        <footer class="footer" id="dash_footer">
            Internet: <span class="{{'' if net else 'offline'}}">{{'Online' if net else 'Offline'}}</span> • Last Boot: {{reboot}} • {{version}}
        </footer>
    </div>

    <div id="toast" class="toast">
        <svg viewBox="0 0 24 24">
            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
        </svg>
        <span>Done</span>
    </div>

    <script>
        function showToast(msg){
            const t = document.getElementById('toast');
            t.querySelector('span').innerText = msg;
            t.classList.add('show');
            setTimeout(() => t.classList.remove('show'), 2200);
        }

        function tick(){
            const d = new Date();
            const p = n => String(n).padStart(2,'0');
            const el = document.getElementById('clock');
            if(el) el.textContent = p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());
        }
        setInterval(tick, 1000); tick();

        function updatePiHoleTimer(){
            const el = document.getElementById('pihole_timer_status');
            if(!el || !el.dataset.pauseUntil) return;
            const left = Math.max(0, Number(el.dataset.pauseUntil) - Math.floor(Date.now() / 1000));
            if(!left){
                el.textContent = 'Pi-hole should now be re-enabled.';
                delete el.dataset.pauseUntil;
                return;
            }
            const hours = Math.floor(left / 3600);
            const minutes = Math.floor((left % 3600) / 60);
            const seconds = left % 60;
            el.innerHTML = 'Blocking re-enables in <strong>' +
                (hours ? hours + ':' : '') + String(minutes).padStart(2, '0') + ':' +
                String(seconds).padStart(2, '0') + '</strong>';
        }
        setInterval(updatePiHoleTimer, 1000); updatePiHoleTimer();

        const escapeHtml = value => String(value).replace(/[&<>'"]/g, c => ({
            '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
        })[c]);

        function queryActionForm(action, domain){
            const safeDomain = escapeHtml(domain);
            const label = action === 'allow' ? 'Allow' : 'Block';
            const cls = action === 'allow' ? '' : ' block';
            return '<form data-query-action action="/queries/domain/' + action + '" method="post">' +
                '<input type="hidden" name="domain" value="' + safeDomain + '">' +
                '<button class="query-action' + cls + '" type="submit">' + label + '</button></form>';
        }

        async function searchQueries(event){
            if(event) event.preventDefault();
            const form = document.getElementById('query_form');
            const params = new URLSearchParams(new FormData(form));
            try {
                const response = await fetch('/queries/search?' + params.toString(), {cache:'no-store'});
                if(!response.ok) throw new Error('Search failed');
                const data = await response.json();
                const scope = data.domain || data.client ? ', matching search' : '';
                document.getElementById('query_blocked').textContent = 'Blocked' + scope + ' (24h): ' + data.summary.blocked;
                document.getElementById('query_allowed').textContent = 'Not blocked' + scope + ' (24h): ' + data.summary.allowed;
                const rows = document.getElementById('query_rows');
                if(data.queries.length){
                    rows.innerHTML = data.queries.map(q => '<tr><td>' + escapeHtml(q.time) + '</td>' +
                        '<td class="query-domain" title="' + escapeHtml(q.domain) + '">' + escapeHtml(q.domain) + '</td>' +
                        '<td>' + escapeHtml(q.client) + '</td><td class="query-status ' +
                        (q.status === 'Blocked' ? 'blocked' : '') + '">' + escapeHtml(q.status) + '</td>' +
                        '<td><div class="query-actions">' + queryActionForm('allow', q.domain) +
                        queryActionForm('block', q.domain) + '</div></td></tr>').join('');
                } else {
                    rows.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:22px;">' +
                        (data.domain || data.client ? 'No recent queries found.' : 'Search a domain or device to see its five most recent queries.') +
                        '</td></tr>';
                }
                history.replaceState({}, '', '/dashboard?' + params.toString() + '#query_search');
            } catch(e) { showToast('Query search failed'); }
        }

        document.getElementById('query_form').addEventListener('submit', searchQueries);
        document.addEventListener('submit', async event => {
            const form = event.target.closest('form[data-query-action]');
            if(!form) return;
            event.preventDefault();
            try {
                const response = await fetch(form.action, {method:'POST', body:new URLSearchParams(new FormData(form))});
                if(!response.ok) throw new Error('Action failed');
                showToast('Pi-hole list updated');
                searchQueries();
            } catch(e) { showToast('Pi-hole action failed'); }
        });

        // Live refresh: update only the dynamic regions every 10s, no full reload
        const REFRESH_IDS = ['hdr_uptime','hdr_status','sp_down','sp_up','sp_meta',
            'st_yt','st_ph','st_vpn','st_bot','st_jelly','st_ts',
            'ph_grid','topdom_list','topcli_list','groups_grid','speedhist',
            'res_grid','adult_list','upd_label','dash_footer'];
        async function refreshData(){
            try {
                const r = await fetch('/dashboard', {cache:'no-store'});
                if(!r.ok) return;
                const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
                if(!doc.getElementById('res_grid')){ location.reload(); return; }  // session expired -> show login
                for(const id of REFRESH_IDS){
                    const cur = document.getElementById(id), nxt = doc.getElementById(id);
                    if(cur && nxt && cur.outerHTML !== nxt.outerHTML) cur.outerHTML = nxt.outerHTML;
                }
            } catch(e){}
        }
        setInterval(refreshData, 10000);

        // Live bandwidth meter: poll /net, compute byte deltas -> throughput
        let _lastNet = null;
        const _rxH = [], _txH = [], _NPTS = 60;
        function fmtRate(bps){
            const b = bps * 8;                       // bytes/s -> bits/s (Mbps style, matches speed test)
            if (b >= 1e9) return (b/1e9).toFixed(2) + ' Gb/s';
            if (b >= 1e6) return (b/1e6).toFixed(1) + ' Mb/s';
            if (b >= 1e3) return (b/1e3).toFixed(0) + ' Kb/s';
            return Math.round(b) + ' b/s';
        }
        function drawSpark(id, data, color){
            const c = document.getElementById(id); if(!c) return;
            const ctx = c.getContext('2d'), w = c.width, h = c.height;
            ctx.clearRect(0,0,w,h);
            if(data.length < 2) return;
            const max = Math.max.apply(null, data.concat([1]));
            const X = i => i/(_NPTS-1)*w;
            const Y = v => h - (v/max)*(h-4) - 2;
            ctx.beginPath();
            data.forEach((v,i)=>{ i ? ctx.lineTo(X(i),Y(v)) : ctx.moveTo(X(i),Y(v)); });
            ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
            ctx.lineTo(X(data.length-1), h); ctx.lineTo(X(0), h); ctx.closePath();
            ctx.fillStyle = color + '22'; ctx.fill();
        }
        async function pollNet(){
            try{
                const r = await fetch('/net', {cache:'no-store'}); if(!r.ok) return;
                const d = await r.json();
                if(_lastNet){
                    const dt = d.t - _lastNet.t;
                    if(dt > 0){
                        let rx = Math.max(0, (d.rx - _lastNet.rx)/dt);
                        let tx = Math.max(0, (d.tx - _lastNet.tx)/dt);
                        document.getElementById('bw_down').textContent = fmtRate(rx);
                        document.getElementById('bw_up').textContent = fmtRate(tx);
                        const ifel = document.getElementById('bw_iface'); if(ifel) ifel.textContent = d.iface;
                        _rxH.push(rx); _txH.push(tx);
                        if(_rxH.length > _NPTS) _rxH.shift();
                        if(_txH.length > _NPTS) _txH.shift();
                        drawSpark('bw_down_spark', _rxH, '#7fb0ff');
                        drawSpark('bw_up_spark', _txH, '#10b981');
                    }
                }
                _lastNet = d;
            }catch(e){}
        }
        setInterval(pollNet, 1500); pollNet();
    </script>
    <script>lucide.createIcons();</script>
</body>
</html>
'''

GROUPS_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="refresh" content="10">
    <title>Groups</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0f1c;
            --bg-secondary: #111827;
            --bg-glass: rgba(17, 24, 39, 0.7);
            --primary: #3b82f6;
            --success: #10b981;
            --danger: #ef4444;
            --text: #f9fafb;
            --border: rgba(255, 255, 255, 0.08);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background: var(--bg-primary); color: var(--text); min-height: 100vh; padding: 24px; }
        .container { max-width: 1000px; margin: auto; }
        header { margin-bottom: 32px; }
        .back-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 14px 24px;
            background: var(--bg-glass);
            border: 1px solid var(--border);
            border-radius: 16px;
            color: var(--text);
            text-decoration: none;
            font-weight: 700;
            transition: all 0.3s ease;
        }
        .back-btn:hover { background: var(--primary); border-color: var(--primary); }
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
        @media (min-width: 768px) { .grid { grid-template-columns: repeat(3, 1fr); } }
        .card {
            background: var(--bg-glass);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 24px;
        }
        .name { font-size: 14px; font-weight: 700; margin-bottom: 8px; }
        .status { font-size: 11px; font-weight: 700; margin-bottom: 16px; text-transform: uppercase; }
        .status.on { color: var(--success); }
        .status.off { color: var(--danger); }
        .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .btn { padding: 12px; text-align: center; border-radius: 12px; font-weight: 700; text-decoration: none; transition: all 0.2s; }
        .btn.on { background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.2); }
        .btn.off { background: rgba(239, 68, 68, 0.1); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.2); }
        .btn:hover { transform: scale(1.05); }
        .btn.on:hover { background: var(--success); color: white; }
        .btn.off:hover { background: var(--danger); color: white; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <a class="back-btn" href="/dashboard">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/>
                </svg>
                Back to Dashboard
            </a>
        </header>
        <div class="grid">
            {% for g in groups %}
            <div class="card">
                <div class="name">{{g.name}}</div>
                <div class="status {{'on' if g.enabled=='1' else 'off'}}">
                    {{'Blocked' if g.enabled=='1' else 'Active'}}
                </div>
                <div class="actions">
                    <a class="btn on" href="/action/group_on/{{g.id}}">ON</a>
                    <a class="btn off" href="/action/group_off/{{g.id}}">OFF</a>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
'''

LOGIN = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Login - Home Server</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body {
            min-height: 100vh;
            background: #0a0f1c;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background:
                radial-gradient(ellipse at 30% 30%, rgba(59, 130, 246, 0.15) 0%, transparent 50%),
                radial-gradient(ellipse at 70% 70%, rgba(139, 92, 246, 0.1) 0%, transparent 50%);
            pointer-events: none;
            z-index: -1;
        }
        .login-box {
            background: rgba(17, 24, 39, 0.8);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 28px;
            padding: 48px;
            width: 100%;
            max-width: 420px;
            text-align: center;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .logo {
            width: 72px;
            height: 72px;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 24px;
            box-shadow: 0 12px 40px rgba(59, 130, 246, 0.4);
        }
        .logo svg { width: 40px; height: 40px; fill: white; }
        h2 { font-size: 26px; font-weight: 800; margin-bottom: 8px; }
        .subtitle { color: #6b7280; font-size: 14px; margin-bottom: 32px; }
        input {
            width: 100%;
            padding: 18px 20px;
            margin-bottom: 16px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.03);
            color: #fff;
            font-size: 16px;
            outline: none;
            transition: all 0.3s ease;
        }
        input:focus {
            border-color: #3b82f6;
            box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15);
        }
        input::placeholder { color: #6b7280; }
        button {
            width: 100%;
            padding: 18px;
            border: none;
            border-radius: 16px;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            color: #fff;
            font-weight: 700;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 40px rgba(59, 130, 246, 0.4);
        }
        button:active { transform: scale(0.98); }
        .error {
            color: #ef4444;
            margin-top: 20px;
            font-size: 14px;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="login-box">
        <div class="logo">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/>
            </svg>
        </div>
        <h2>Welcome Back</h2>
        <p class="subtitle">Enter your admin password</p>
        <form method="post">
            <input type="password" name="password" placeholder="Admin Password" autofocus required>
            <button type="submit">Unlock Dashboard</button>
            {% if msg %}<p class="error">{{msg}}</p>{% endif %}
        </form>
    </div>
</body>
</html>
'''

# ==================================================
# ROUTES
# ==================================================
@app.route("/", methods=["GET", "POST"])
def login():
    if logged():
        return redirect("/dashboard")
    msg = ""
    if request.method == "POST":
        if request.form.get("password") == PASSWORD:
            session["ok"] = 1
            return redirect("/dashboard")
        msg = "Wrong Password"
    return render_template_string(LOGIN, msg=msg)

@app.route("/dashboard")
def dashboard():
    if not logged():
        return redirect("/")
    queries, query_domain, query_client = recent_queries(
        request.args.get("domain", ""), request.args.get("client", ""))
    query_return = "/dashboard?" + urlencode({"domain": query_domain, "client": query_client})
    return render_template_string(
        HTML,
        version=VERSION,
        net=internet(),
       vpn=svc("openvpn-client@proton.service"),
        ph=pihole(),
        pause=pihole_pause_state(),
        queries=queries,
        query_domain=query_domain,
        query_client=query_client,
        query_summary=query_counts_24h(query_domain, query_client),
        query_return=query_return,
        phstats=pihole_stats(),
        topdom=top_blocked(),
        topcli=top_clients(),
        adult=adult_attempts(),
        yt=youtube_status(),
        bot=svc("tg-control.timer"),
        jelly=svc("jellyfin"),
        fb=svc("filebrowser"),
        tailscale=svc("tailscaled"),
        uptime=uptime(),
        cpu=cpu(),
        ram=ram(),
        disk=disk(),
        temp=temp(),
        reboot=reboot_info(),
        upd=updates_count(),
        groups=pihole_groups(),
        spd=speedtest(),
        spdhist=speed_history(),
        bat=battery(),
        cronjobs=cron_jobs()
    )

@app.route("/groups")
def groups():
    if not logged():
        return redirect("/")
    return render_template_string(GROUPS_HTML, groups=pihole_groups())

@app.route("/net")
def net():
    if not logged():
        return ("", 401)
    return (json.dumps(net_counters()), 200, {"Content-Type": "application/json"})

@app.route("/queries/search")
def queries_search():
    if not logged():
        return (json.dumps({"error": "Not logged in"}), 401, {"Content-Type": "application/json"})
    queries, domain, client = recent_queries(request.args.get("domain", ""), request.args.get("client", ""))
    return (json.dumps({"queries": queries, "domain": domain, "client": client,
                        "summary": query_counts_24h(domain, client)}),
            200, {"Content-Type": "application/json"})

@app.route("/pihole/pause", methods=["POST"])
def pihole_pause():
    if not logged():
        return redirect("/")
    try:
        minutes = int(request.form.get("minutes", ""))
    except (TypeError, ValueError):
        return redirect("/dashboard")
    # Pi-hole accepts duration strings such as "30m" and schedules its own
    # automatic re-enable, so the timer survives a dashboard restart.
    if 1 <= minutes <= 1440:
        result = subprocess.run(["sudo", "pihole", "disable", f"{minutes}m"], check=False)
        if result.returncode == 0:
            with open(PIHOLE_PAUSE_STATE, "w") as f:
                json.dump({"ends_at": int(time.time()) + minutes * 60}, f)
    return redirect("/dashboard")

def update_domain_list(action, domain):
    domain = (domain or "").strip().lower()
    # DNS names from FTL are plain ASCII/punycode. Restrict input before it is
    # supplied to the Pi-hole CLI, even though this command does not use a shell.
    if action in {"allow", "block"} and re.fullmatch(r"[a-z0-9.-]{1,253}", domain):
        command = "allow" if action == "allow" else "deny"
        try:
            return subprocess.run(["sudo", "pihole", command, domain], check=False, timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    return False

@app.route("/queries/domain/<action>", methods=["POST"])
def query_domain_action(action):
    if not logged():
        return (json.dumps({"ok": False}), 401, {"Content-Type": "application/json"})
    ok = update_domain_list(action, request.form.get("domain"))
    return (json.dumps({"ok": ok}), 200 if ok else 400, {"Content-Type": "application/json"})

@app.route("/domain/<action>", methods=["POST"])
def domain_action(action):
    if not logged():
        return redirect("/")
    update_domain_list(action, request.form.get("domain"))
    return_to = request.form.get("return_to", "")
    return redirect(return_to if return_to.startswith("/dashboard?") else "/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/action/cron_toggle/<user>/<int:line_idx>")
def cron_toggle(user, line_idx):
    if not logged():
        return redirect("/")
    if user in ["saif", "root"]:
        try:
            raw = sh(f"crontab -u {user} -l 2>/dev/null")
            lines = raw.splitlines()
            if 0 <= line_idx < len(lines):
                line = lines[line_idx].strip()
                if line.startswith("#"):
                    lines[line_idx] = line.lstrip("#").strip()
                else:
                    lines[line_idx] = "# " + line
                new_crontab = "\n".join(lines) + "\n"
                p = subprocess.run(["crontab", "-u", user, "-"], input=new_crontab, text=True, capture_output=True)
        except:
            pass
    return redirect("/dashboard")

@app.route("/action/cron_edit", methods=["POST"])
def cron_edit():
    if not logged():
        return redirect("/")
    user = request.form.get("user")
    try:
        line_idx = int(request.form.get("line_idx", -1))
    except:
        line_idx = -1
    new_sched = request.form.get("schedule", "").strip()
    
    if user in ["saif", "root"] and line_idx >= 0 and new_sched:
        try:
            raw = sh(f"crontab -u {user} -l 2>/dev/null")
            lines = raw.splitlines()
            if 0 <= line_idx < len(lines):
                line = lines[line_idx].strip()
                is_disabled = line.startswith("#")
                clean_line = line.lstrip("#").strip()
                
                parts = clean_line.split(None, 5)
                if len(parts) >= 6:
                    cmd = parts[5]
                else:
                    cmd = clean_line
                
                updated_line = f"{new_sched} {cmd}"
                if is_disabled:
                    updated_line = "# " + updated_line
                
                lines[line_idx] = updated_line
                new_crontab = "\n".join(lines) + "\n"
                subprocess.run(["crontab", "-u", user, "-"], input=new_crontab, text=True, capture_output=True)
        except:
            pass
    return redirect("/dashboard")

@app.route("/action/<path:name>")
def action(name):
    if not logged():
        return redirect("/")
    if name == "pihole_on":
        clear_pihole_pause_state()
    if name.startswith("group_on/"):
        gid = name.split("/")[-1]
        subprocess.run(f"sudo sqlite3 /etc/pihole/gravity.db \"update 'group' set enabled=1 where id={gid};\" && sudo pihole reloadlists", shell=True)
        return redirect("/dashboard")

    if name.startswith("group_off/"):
        gid = name.split("/")[-1]
        subprocess.run(f"sudo sqlite3 /etc/pihole/gravity.db \"update 'group' set enabled=0 where id={gid};\" && sudo pihole reloadlists", shell=True)
        return redirect("/dashboard")

    cmds = {
        "youtube_on": "bash /usr/local/bin/youtube_on.sh",
        "youtube_off": "bash /usr/local/bin/youtube_off.sh",
        "pihole_on": "pihole enable",
        "pihole_off": "pihole disable",
        "vpn_on": "systemctl start openvpn-client@proton",
        "vpn_off": "systemctl stop openvpn-client@proton",
        "tg_on": "systemctl start tg-control.timer",
        "tg_off": "systemctl stop tg-control.timer",
        "jellyfin_on": "systemctl start jellyfin filebrowser",
        "jellyfin_off": "systemctl stop jellyfin filebrowser",
        "tailscale_on": "systemctl start tailscaled",
        "tailscale_off": "systemctl stop tailscaled",
            "tailscale_fix": "systemctl restart tailscaled && tailscale up",
        "restart_all": "systemctl restart openvpn-client@proton tg-control.timer tailscaled jellyfin filebrowser",
        "update_system": "bash -c 'DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef upgrade' > /tmp/update.log 2>&1",
        "pihole_update": "pihole -up -y > /tmp/pihole_update.log 2>&1",
        "rollback": "/usr/local/bin/dashboard_manager.sh rollback-latest",
        "manual_speedtest": "/usr/local/bin/run_speedtest.sh",
        "reboot": "reboot"
    }
    # Long-running jobs must not block the HTTP request (otherwise the browser
    # hangs/times out). Run them detached and let the dashboard auto-refresh
    # show the result when they finish.
    bg = {"update_system", "manual_speedtest", "pihole_update"}
    if name in cmds:
        full = "sudo " + cmds[name]
        if name in bg:
            subprocess.Popen("setsid " + full, shell=True)
        else:
            subprocess.run(full, shell=True)
    return redirect("/dashboard")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088, threaded=True)
