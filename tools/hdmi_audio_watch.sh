#!/usr/bin/env bash
# HDMI のモニターがつながっているのに、PipeWire に HDMI の音声出力がない場合に、WirePlumber を再起動して
# 判断し直させる（あわせて音声アシスタントも起動し直す）。systemd のタイマーから 30 秒ごとに実行される。
#
# 背景：Pi の起動時にモニターの電源が入っていないと、WirePlumber が HDMI の音声出力を「使えない」と判断し、
# あとでモニターがついても判断し直さない（2026-09-19 確認）。
# USB スピーカーに替えた場合は不要（タイマーを止める：systemctl --user disable --now voice-assistant-hdmi-watch.timer）。
set -u

cd "$(dirname "$0")/.."
LOG="logs/conversation.log"
STAMP="${XDG_RUNTIME_DIR:-/tmp}/voice-assistant-hdmi-watch.last"
MIN_INTERVAL=600      # 直したあと、これだけの秒数は直しに行かない（モニターの省電力中などに再起動を繰り返さないため）
WIREPLUMBER_GRACE=30  # WirePlumber が起動してから間もないときは、出力の準備中かもしれないので様子を見る

connected=false
for status in /sys/class/drm/card*-HDMI-A-*/status; do
    [ "$(cat "$status" 2>/dev/null)" = connected ] && connected=true
done
$connected || exit 0

pactl list sinks short 2>/dev/null | grep -q hdmi && exit 0

now=$(date +%s)
started=$(systemctl --user show wireplumber -p ActiveEnterTimestamp --value)
if [ -n "$started" ] && [ $((now - $(date -d "$started" +%s))) -lt "$WIREPLUMBER_GRACE" ]; then
    exit 0
fi
if [ -e "$STAMP" ] && [ $((now - $(cat "$STAMP"))) -lt "$MIN_INTERVAL" ]; then
    exit 0
fi
echo "$now" > "$STAMP"

message="HDMI のモニターがつながっているのに音声出力がないため、音の設定を読み込み直します"
echo "$message"
mkdir -p "$(dirname "$LOG")"
echo "$(date '+%m/%d %H:%M:%S')  状態：$message" >> "$LOG"

systemctl --user restart wireplumber
for _ in $(seq 1 15); do
    pactl list sinks short 2>/dev/null | grep -q hdmi && break
    sleep 1
done
if systemctl --user is-active --quiet voice-assistant; then
    systemctl --user restart voice-assistant
fi
