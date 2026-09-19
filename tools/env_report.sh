#!/usr/bin/env bash
# Pi の実行環境を Markdown で出力する。docs/verified-environments.md に追記する記録のもとにする。
# ユーザー名・ホスト名・IP アドレスは出力しない。
#
# 使い方（PC から）：ssh raspi-voice 'bash ~/voice-assistant/tools/env_report.sh'
# 出力の <…> の部分（確認した範囲・結果）は手で埋める。
set -euo pipefail

cd "$(dirname "$0")/.."

os_name=$(. /etc/os-release && echo "$PRETTY_NAME")
image=$(head -n1 /etc/rpi-issue 2>/dev/null || echo "不明")
model=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "不明")
mem=$(awk '/MemTotal/ {printf "%.1f GiB", $2 / 1024 / 1024}' /proc/meminfo)

echo "## $(date +%Y-%m-%d)：<確認した範囲>"
echo
echo "- 結果：<確認した内容と結果>"
echo "- 機体：${model}（メモリ ${mem}）"
echo "- OS：${os_name}（イメージ：${image}）"
echo "- カーネル：$(uname -r)（$(uname -m)、ページサイズ $(getconf PAGESIZE)）"
echo "- Python：$(venv/bin/python --version 2>&1 | cut -d' ' -f2)（pip $(venv/bin/pip --version | cut -d' ' -f2)）"
echo
echo "apt パッケージ（tools/apt-packages.txt に載せているもの）："
echo
echo '```'
sed 's/#.*//' tools/apt-packages.txt | xargs -n1 | while read -r pkg; do
    dpkg-query -W -f='${Package}=${Version}\n' "$pkg" 2>/dev/null || echo "${pkg}=（未導入）"
done
echo '```'
echo
echo "pip パッケージ（venv の pip freeze。このまま requirements として使える）："
echo
echo '```'
venv/bin/pip freeze
echo '```'
echo
echo "モデル（tools/models.txt に載せているもの。SHA-256 の先頭 16 文字）："
echo
echo '```'
sed 's/#.*//' tools/models.txt | awk 'NF {print $1}' | while read -r path; do
    if [ -e "$path" ]; then
        echo "${path}  $(sha256sum "$path" | cut -c1-16)"
    else
        echo "${path}  （なし）"
    fi
done
echo '```'
