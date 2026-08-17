#!/usr/bin/env python3
import os, time, subprocess, urllib.request, json

TELEGRAM_TOKEN_FILE = "/home/saif/.telegram_token"
TELEGRAM_CHAT_FILE = "/home/saif/.telegram_chat"

def send_telegram(msg):
    try:
        tokens = []
        chats = []
        if os.path.exists(TELEGRAM_TOKEN_FILE):
            t = open(TELEGRAM_TOKEN_FILE).read().strip()
            if t: tokens.append(t)
        # Also support second token file if configured
        if os.path.exists("/home/saif/.telegram_token_2"):
            t2 = open("/home/saif/.telegram_token_2").read().strip()
            if t2: tokens.append(t2)
        if not tokens and os.path.exists(TELEGRAM_TOKEN_FILE):
            tokens = [open(TELEGRAM_TOKEN_FILE).read().strip()]

        if os.path.exists(TELEGRAM_CHAT_FILE):
            c = open(TELEGRAM_CHAT_FILE).read().strip()
            if c: chats.append(c)
        if os.path.exists("/home/saif/.telegram_chat_2"):
            c2 = open("/home/saif/.telegram_chat_2").read().strip()
            if c2: chats.append(c2)
        if not chats and os.path.exists(TELEGRAM_CHAT_FILE):
            chats = [open(TELEGRAM_CHAT_FILE).read().strip()]

        for token in tokens:
            for chat_id in chats:
                if token and chat_id:
                    try:
                        data = json.dumps({'chat_id': chat_id, 'text': msg}).encode()
                        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, headers={'Content-Type': 'application/json'})
                        res = urllib.request.urlopen(req, timeout=5)
                        print(f"Telegram sent to {chat_id}: status {res.status}")
                    except Exception as ex:
                        print(f"Telegram send failed for {chat_id}: {ex}")
    except Exception as e:
        print("Telegram error:", e)

def check_services():
    # Watchdog: check critical services (dashboard, tailscale) and restart if down
    services = ["dashboard.service", "tailscaled.service"]
    for svc in services:
        status = subprocess.run(f"systemctl is-active {svc}", shell=True, capture_output=True, text=True).stdout.strip()
        if status != "active":
            print(f"Service {svc} is down! Restarting...")
            subprocess.run(f"sudo systemctl restart {svc}", shell=True)
            send_telegram(f"⚠️ Watchdog Alert: Service {svc} went down and was automatically restarted!")

def poll_telegram_bot():
    try:
        if not (os.path.exists(TELEGRAM_TOKEN_FILE) and os.path.exists(TELEGRAM_CHAT_FILE)):
            return
        token = open(TELEGRAM_TOKEN_FILE).read().strip()
        offset_file = "/tmp/telegram_bot_offset.txt"
        offset = 0
        if os.path.exists(offset_file):
            offset = int(open(offset_file).read().strip() or 0)
        
        url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=2"
        req = urllib.request.urlopen(url, timeout=5)
        res = json.loads(req.read().decode())
        if res.get("ok"):
            for update in res.get("result", []):
                new_offset = update["update_id"] + 1
                open(offset_file, 'w').write(str(new_offset))
                
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))
                
                if text.startswith("/"):
                    cmd = text.split()[0].lower()
                    response = "Unknown command. Available: /status, /speedtest, /reboot, /pihole_pause"
                    if cmd == "/status":
                        cpu = subprocess.run("top -bn1 | grep 'Cpu(s)' | awk '{print 15 - $8}'", shell=True, capture_output=True, text=True).stdout.strip() or "N/A"
                        ram = subprocess.run("free | grep Mem | awk '{print $3/$2 * 100.0}'", shell=True, capture_output=True, text=True).stdout.strip()
                        response = f"🖥️ Server Status (Dashboard v1.9)\nCPU Usage: {cpu}%\nRAM Usage: {float(ram):.1f}%\nStatus: Online 🟢"
                    elif cmd == "/speedtest":
                        send_telegram("🚀 Running speedtest... Please wait.")
                        res_st = subprocess.run("speedtest-cli --simple 2>/dev/null || echo 'Speedtest failed'", shell=True, capture_output=True, text=True).stdout.strip()
                        response = f"📊 Speedtest Result:\n{res_st}"
                    elif cmd == "/reboot":
                        send_telegram("🔄 Rebooting server now...")
                        subprocess.run("sudo reboot", shell=True)
                        response = "Server reboot initiated."
                    elif cmd == "/pihole_pause":
                        subprocess.run("pihole disable 300", shell=True)
                        response = "🛡️ Pi-hole paused for 5 minutes."
                    
                    if chat_id:
                        data = json.dumps({'chat_id': chat_id, 'text': response}).encode()
                        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, headers={'Content-Type': 'application/json'}, timeout=5)
    except Exception as e:
        pass

def check_adidas_order():
    try:
        state_file = "/home/saif/.adidas_order_state.json"
        import time
        now = time.time()
        # Check every 1 hour (3600 seconds)
        is_first_check = False
        if os.path.exists(state_file):
            data = json.load(open(state_file))
            if now - data.get("last_check", 0) < 3600:
                return
        else:
            is_first_check = True

        tracking_url = "https://adidas.clickpost.in/?waybill=GS1315368898&cm_mmc=AdiEmail_OLC-_-None-_-Shipping_Confirmation.Complete-_-Transactional-_-MainstoryCTA1-_-dv:eCom-_-cn:Order_Related-_-pc:None&cm_mmc1=IN&cm_mmca3=5UG9WTMXIIX84LDI&cm_mmca4=4238240&cm_mmc2=adidas-ROW-eCom-Email-OLC-None-None-IN-Order_Related-None-2608&af_reengagement_window=30d&is_retargeting=true&pid=sfmc&c=adidas-ROW-eCom-Email-OLC-None-None-IN-Order_Related-None-2608&af_adset=Shipping_Confirmation.Complete&af_ad=MainstoryCTA1&af_channel=Order_Related"
        
        prefix = "🚨 [FIRST CHECK ALERT] " if is_first_check else "📦 [HOURLY CHECK] "
        msg = f"{prefix}Adidas Order Tracking (GS1315368898):\nYour order tracking status update. Check latest status here:\n{tracking_url}"
        send_telegram(msg)
        
        with open(state_file, "w") as f:
            json.dump({"last_check": now}, f)
    except Exception as e:
        print("Adidas order check error:", e)

if __name__ == '__main__':
    last_order_run = 0
    while True:
        check_services()
        poll_telegram_bot()
        try:
            check_adidas_order()
        except:
            pass
        time.sleep(15)
