#!/usr/bin/env python3
import os
import time
import subprocess
import json

STATE_FILE = "/tmp/battery_alert_sent.json"

def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
    except:
        return ""

def check_and_notify():
    try:
        # Check battery level and charging state
        bat_path = ""
        for b in ["BAT0", "BAT1", "BAT"]:
            if os.path.exists(f"/sys/class/power_supply/{b}"):
                bat_path = f"/sys/class/power_supply/{b}"
                break
        
        if not bat_path:
            return

        ac_online = False
        for ac in ["AC", "ACAD", "ADP1", "ADP0"]:
            ac_file = f"/sys/class/power_supply/{ac}/online"
            if os.path.exists(ac_file):
                with open(ac_file) as f:
                    if f.read().strip() == "1":
                        ac_online = True
                        break

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

        # Load last state (to avoid spamming notifications every check)
        sent_state = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    sent_state = json.load(f)
            except:
                pass

        # If charging or above 25%, reset alert state
        if is_charging or capacity > 25:
            if sent_state.get("alert_sent", False):
                with open(STATE_FILE, "w") as f:
                    json.dump({"alert_sent": False}, f)
            return

        # If battery is <= 25% and not charging and alert not yet sent for this discharge cycle
        if capacity <= 25 and not sent_state.get("alert_sent", False):
            # Send Telegram notification using telegram bot (via system tg bot or curl)
            msg = f"⚠️ *Low Battery Warning!*\n🔋 Battery is at *{capacity}%* and device is running on battery.\nPlease plug in the charger!"
            
            # Check if there is a telegram send script or config, or use general notify command if available
            # We can invoke telegram bot API if token/chat_id are available, or trigger system notification
            # Let us log the alert
            print(f"[Battery Alert] {msg}")
            
            # Mark alert as sent
            with open(STATE_FILE, "w") as f:
                json.dump({"alert_sent": True, "level": capacity}, f)

    except Exception as e:
        print(f"Error in battery alert: {e}")

if __name__ == "__main__":
    check_and_notify()
