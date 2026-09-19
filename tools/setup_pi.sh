#!/usr/bin/env bash
# Pi 上で実行環境を準備する：apt パッケージ、venv、Python パッケージ、モデル、WirePlumber の設定、
# 自動起動（systemd のユーザーサービス）、.env のひな形。
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

echo "== モデル"
# tools/models.txt の各行：保存先 URL SHA-256。ない場合だけダウンロードし、どちらの場合も SHA-256 を確かめる
while read -r dest url sha256; do
    if [ ! -e "$dest" ]; then
        echo "ダウンロードします：$dest"
        mkdir -p "$(dirname "$dest")"
        curl -fsSL --retry 3 -o "$dest.part" "$url"
        if ! echo "$sha256  $dest.part" | sha256sum -c --quiet - >/dev/null 2>&1; then
            rm -f "$dest.part"
            echo "SHA-256 が一致しません（ダウンロードしたファイルは削除しました）：$url" >&2
            exit 1
        fi
        mv "$dest.part" "$dest"
    elif ! echo "$sha256  $dest" | sha256sum -c --quiet - >/dev/null 2>&1; then
        echo "SHA-256 が一致しません（手で確認してください）：$dest" >&2
        exit 1
    fi
    echo "OK：$dest"
    # zip は同じ名前のフォルダ（例：models/xxx.zip → models/xxx/）に展開する
    if [[ "$dest" == *.zip ]] && [ ! -d "${dest%.zip}" ]; then
        echo "展開します：$dest"
        venv/bin/python -m zipfile -e "$dest" "$(dirname "$dest")"
        if [ ! -d "${dest%.zip}" ]; then
            echo "展開後のフォルダが見つかりません：${dest%.zip}" >&2
            exit 1
        fi
    fi
done < <(sed 's/#.*//' tools/models.txt | awk 'NF')

echo "== WirePlumber の設定（HDMI の音声出力を休止させない）"
wp_src="tools/pi-config/wireplumber/51-voice-assistant-hdmi-no-suspend.lua"
wp_dir="$HOME/.config/wireplumber/main.lua.d"
if cmp -s "$wp_src" "$wp_dir/$(basename "$wp_src")"; then
    echo "設定済み"
else
    mkdir -p "$wp_dir"
    cp "$wp_src" "$wp_dir/"
    echo "配置しました：$wp_dir/$(basename "$wp_src")"
    echo "WirePlumber を再起動します（HDMI モニターが一瞬消えることがあります）"
    systemctl --user restart wireplumber
fi

echo "== 自動起動（systemd のユーザーサービス・タイマー）"
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
assistant_changed=false
units_changed=false
for unit_src in tools/pi-config/systemd/*.service tools/pi-config/systemd/*.timer; do
    unit=$(basename "$unit_src")
    if cmp -s "$unit_src" "$unit_dir/$unit"; then
        echo "設定済み：$unit"
    else
        cp "$unit_src" "$unit_dir/"
        echo "配置しました：$unit_dir/$unit"
        units_changed=true
        [ "$unit" = voice-assistant.service ] && assistant_changed=true
    fi
done
if $units_changed; then
    systemctl --user daemon-reload
fi
if $assistant_changed && systemctl --user is-active --quiet voice-assistant; then
    systemctl --user restart voice-assistant
    echo "動いていた音声アシスタントを再起動しました"
fi
if ! systemctl --user is-enabled --quiet voice-assistant; then
    systemctl --user enable voice-assistant
    echo "音声アシスタントの自動起動を有効にしました（次に Pi を起動したときから。今すぐ起動するには：systemctl --user start voice-assistant）"
fi
# HDMI の音声出力を見張るタイマー（起動時にモニターの電源が入っていなかった場合に直す）
if ! systemctl --user is-enabled --quiet voice-assistant-hdmi-watch.timer; then
    systemctl --user enable --now voice-assistant-hdmi-watch.timer
    echo "HDMI の音声出力を見張るタイマーを有効にしました"
fi

echo "== .env"
if [ -e .env ]; then
    echo ".env はあります（変更しません）"
else
    cp .env.example .env
    chmod 600 .env
    echo ".env を作成しました。GEMINI_API_KEY などを記入してください：nano ~/voice-assistant/.env"
fi

echo "== 完了"
