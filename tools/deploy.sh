#!/usr/bin/env bash
# PC から Pi へプログラムを配置する（PC の Git Bash で、リポジトリのどこからでも実行できる）。
#
# 使い方：tools/deploy.sh [SSH の別名]    （省略時は raspi-voice）
#
# Pi の ~/voice-assistant/ にある DEPLOY_ITEMS をいったん消してから送り直すため、
# PC 側で削除・名前変更したファイルは Pi からも消える。
# venv・.env・models・recordings など、DEPLOY_ITEMS 以外のものには触らない。
set -euo pipefail

HOST="${1:-raspi-voice}"
REMOTE_DIR="voice-assistant"   # Pi のホームディレクトリからの相対パス
DEPLOY_ITEMS=(voice_assistant scripts tools config requirements.txt .env.example)

cd "$(dirname "$0")/.."

for item in "${DEPLOY_ITEMS[@]}"; do
    if [ ! -e "$item" ]; then
        echo "見つかりません：$item" >&2
        exit 1
    fi
done

echo "配置先：${HOST}:~/${REMOTE_DIR}/"
tar -cf - --exclude='__pycache__' --exclude='*.pyc' "${DEPLOY_ITEMS[@]}" |
    ssh "$HOST" "set -eu
        mkdir -p ~/${REMOTE_DIR}
        cd ~/${REMOTE_DIR}
        rm -rf .deploy-tmp
        mkdir .deploy-tmp
        tar -xf - -C .deploy-tmp
        for item in ${DEPLOY_ITEMS[*]}; do
            rm -rf \"\$item\"
            mv \".deploy-tmp/\$item\" .
        done
        rmdir .deploy-tmp
        chmod +x tools/*.sh"
echo "配置しました。初回や requirements.txt・tools/apt-packages.txt を変えたときは、Pi 上で tools/setup_pi.sh を実行してください。"
