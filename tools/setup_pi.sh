#!/usr/bin/env bash
# Pi 上で実行環境を準備する：apt パッケージ、venv、Python パッケージ、.env のひな形。
# 何度実行してもよい（導入済みのものはそのまま。.env があれば触らない）。
#
# 使い方（Pi 上で）：bash ~/voice-assistant/tools/setup_pi.sh
# PC から：ssh raspi-voice 'bash ~/voice-assistant/tools/setup_pi.sh'
#   （sudo にパスワードが必要な機体では ssh -t を付ける）
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== apt パッケージ"
mapfile -t packages < <(sed 's/#.*//' tools/apt-packages.txt | xargs -n1)
missing=()
for pkg in "${packages[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
        missing+=("$pkg")
    fi
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "導入します：${missing[*]}"
    sudo apt-get update
    sudo apt-get install -y "${missing[@]}"
else
    echo "すべて導入済み：${packages[*]}"
fi

echo "== Python の仮想環境"
if [ ! -x venv/bin/python ]; then
    python3 -m venv venv
    echo "venv を作成しました"
fi
venv/bin/pip install -r requirements.txt

echo "== .env"
if [ -e .env ]; then
    echo ".env はあります（変更しません）"
else
    cp .env.example .env
    chmod 600 .env
    echo ".env を作成しました。GEMINI_API_KEY などを記入してください：nano ~/voice-assistant/.env"
fi

echo "== 完了"
