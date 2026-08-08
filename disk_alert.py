#!/usr/bin/env python3
import os, subprocess

TELEGRAM_TOKEN_FILE = "/home/saif/.telegram_token"
TELEGRAM_CHAT_FILE = "/home/saif/.telegram_chat"

def send_telegram(msg):
    try:
        if os.path.exists(TELEGRAM_TOKEN_FILE) and os.path.exists(TELEGRAM_CHAT_FILE):
            token = open(TELEGRAM_TOKEN_FILE).read().strip()
            chat_id = open(TELEGRAM_CHAT_FILE).read().strip()
            if token and chat_id:
                import urllib.request, urllib.parse
                data = urllib.parse.urlencode({'chat_id': chat_id, 'text': msg}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=5)
    except Exception as e:
        print("Telegram error:", e)

def check_disk():
    try:
        out = subprocess.run("df / | tail -1", shell=True, capture_output=True, text=True).stdout.strip()
        parts = out.split()
        if len(parts) >= 5:
            pct = int(parts[4].replace('%', ''))
            state_file = "/tmp/disk_alert_sent"
            if pct >= 85:
                if not os.path.exists(state_file):
                    send_telegram(f"⚠️ Disk Space Warning! Root partition usage is at {pct}%. Please clean up disk space.")
                    open(state_file, 'w').write('1')
            else:
                if os.path.exists(state_file):
                    os.remove(state_file)
    except Exception as e:
        print("Disk check error:", e)

if __name__ == '__main__':
    check_disk()
