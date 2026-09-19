#!/usr/bin/env bash
# 音声アシスタントの会話ログを表示し続ける（新しいやり取りは自動で追加表示される）。
#
# 使い方（Pi 上で）：デスクトップの「会話ログ」アイコンをダブルクリックする
#   （tools/pi-config/desktop/voice-assistant-log.desktop を ~/Desktop に置いた場合。docs/setup.md 参照）
#   または、ターミナルで ~/voice-assistant/tools/show_conversation.sh
# 閉じるときはウィンドウを閉じるか Ctrl+C。音声アシスタント本体は止まらない。
set -u

LOG="$(cd "$(dirname "$0")/.." && pwd)/logs/conversation.log"

printf '\033]0;音声アシスタント 会話ログ\007'  # ウィンドウのタイトル
echo "=== 音声アシスタントの会話ログ ==="
echo "新しいやり取りは自動で表示されます。閉じるときはウィンドウを閉じるか Ctrl+C を押してください。"
echo
if [ ! -e "$LOG" ]; then
    echo "（まだ会話ログがありません。音声アシスタントが動き始めると表示されます）"
fi
# -F：ファイルがまだない場合や、毎日 0 時にファイルが切り替わった場合も追い続ける。
# そのときに tail が出す案内（標準エラー）は表示しない。
exec tail -n 50 -F "$LOG" 2>/dev/null
