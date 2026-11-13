#!/bin/bash
# Robust internet speed test.
#  - Retries on the flaky speedtest-cli transient failures (common on-the-hour).
#  - Only records a result when it is valid; never overwrites good data with zeros.
#  - Logs each attempt to /tmp/speedtest_run.log for troubleshooting.

ATTEMPTS=4        # number of tries before giving up
DELAY=20          # seconds to wait between tries
# Results live in the dashboard user's home, not /tmp, so the history
# survives the weekly reboot. The log stays in /tmp on purpose.
DATA_DIR=/home/saif/.dashboard_speedtest
HIST=$DATA_DIR/history.txt
CUR=$DATA_DIR/latest.txt
LOG=/tmp/speedtest_run.log
mkdir -p "$DATA_DIR"

valid() {
    # args: down up ping  -> valid if down>0 and up>0 and 0<ping<100000 ms
    awk -v d="$1" -v u="$2" -v p="$3" 'BEGIN{
        if (d+0>0 && u+0>0 && p+0>0 && p+0<100000) exit 0; else exit 1 }'
}

for i in $(seq 1 "$ATTEMPTS"); do
    OUT=$(speedtest-cli --simple --secure 2>>"$LOG")
    DOWN=$(echo "$OUT" | awk '/Download/{print $2}')
    UP=$(echo   "$OUT" | awk '/Upload/{print $2}')
    PING=$(echo "$OUT" | awk '/Ping/{print $2}')

    if valid "$DOWN" "$UP" "$PING"; then
        NOW=$(date '+%Y-%m-%d %H:%M')
        echo "$DOWN|$UP|$PING|$NOW" > "$CUR"
        echo "$DOWN|$UP|$PING|$NOW" >> "$HIST"
        tail -n 50 "$HIST" > "${HIST}.tmp" && mv "${HIST}.tmp" "$HIST"
        chmod 644 "$CUR" "$HIST"
        echo "[$(date '+%F %T')] OK attempt $i: ${DOWN}/${UP}/${PING}" >> "$LOG"
        exit 0
    fi

    echo "[$(date '+%F %T')] FAIL attempt $i (down='$DOWN' up='$UP' ping='$PING')" >> "$LOG"
    [ "$i" -lt "$ATTEMPTS" ] && sleep "$DELAY"
done

# All attempts failed: keep the previous good result, do NOT write zeros.
echo "[$(date '+%F %T')] all $ATTEMPTS attempts failed; kept previous result" >> "$LOG"
exit 1
