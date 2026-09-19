# セットアップ手順（新しい Raspberry Pi に環境を作る）

Pi を初期化して作り直すときや、機体を増やすときに使う手順書。
**Pi に入れるもの（apt・pip・モデル）やシステム設定を変えたら、同じ変更の中でこのファイルも更新する。**

接続先の IP アドレス・ユーザー名・パスワード・API キーはこのファイルに書かない（`<ユーザー名>` のように書く）。

## 0. 現在の推奨環境

この手順書と `requirements.txt` が対象としている環境。過去に動作確認した環境と、そのときのパッケージの版は
[verified-environments.md](verified-environments.md) を参照する。

| 項目 | 内容 |
|---|---|
| 本体 | Raspberry Pi 5（16GB）、電源 5V/5A、ファン付き |
| OS | Raspberry Pi OS (64-bit)、Debian 12 bookworm ベース（イメージ 2025-05-13） |
| カーネル | 6.12 系、ページサイズ 16KB（Pi 5 の標準） |
| Python | 3.11.2 |
| マイク | USB マイク（C-Media 製 USB PnP Audio Device、録音専用） |
| スピーカー | HDMI モニターのスピーカー（将来 USB スピーカーに変更予定） |

**OS のバージョンに注意**：Raspberry Pi Imager の既定の OS は、この環境より新しい版（Debian 13 trixie ベース、
Python も新しい版）になっている可能性がある（未確認）。その場合、パッケージのバージョンや手順が合わないことがある。
次のどちらかにする。
- Imager で bookworm ベースの版（「Legacy」などの名前で提供されている場合がある）を選ぶ
- 新しい版で動作確認し直し、このファイルと `requirements.txt` を更新する。確認結果は
  verified-environments.md に追記する（bookworm での記録はそのまま残す）

## 1. SD カードの作成（PC の Raspberry Pi Imager）

- デバイス：Raspberry Pi 5、OS：Raspberry Pi OS (64-bit)（上の注意を参照）
- 「OS のカスタマイズ」で次を設定する
  - **ホスト名は機体ごとに変える**（例：`voice-01`、`voice-02`）。既定の `raspberrypi` のままだと複数台で区別できない
  - ユーザー名・パスワード（パスワードはどこにも書き残さない）
  - Wi-Fi（使う場合）、タイムゾーン `Asia/Tokyo`、キーボード `jp`
  - SSH を有効にし、**公開鍵認証のみ**にして PC の公開鍵を登録する

## 2. PC の SSH 設定

`~/.ssh/config` に別名を登録する（このファイルはリポジトリの外。値は機体ごとに記入）。

```
Host raspi-voice
    HostName <ホスト名>.local
    User <ユーザー名>
    IdentityFile ~/.ssh/<秘密鍵のファイル名>
```

- 機体を増やす場合は別名を分ける（例：`raspi-voice-2`）。以降の手順の `raspi-voice` をその別名に読み替える。
- **同じホスト名・IP で作り直した場合**、Pi の SSH ホスト鍵が変わるため接続時に警告が出る。
  作り直したことが確かなら、PC で古い鍵を消してから接続する：`ssh-keygen -R <ホスト名>.local`
- 確認：`ssh raspi-voice hostname` がパスワードなしで通ること。

## 3. ハードウェアの確認（参照系のみ）

| 確認 | コマンド | 期待する結果 |
|---|---|---|
| 64bit | `getconf LONG_BIT` | `64` |
| OS | `cat /etc/os-release` | 上の「現在の推奨環境」と同じ版 |
| Python | `python3 --version` | 3.11.x（違う場合は 0 の注意を参照） |
| 電源 | `od -An -tu4 --endian=big /proc/device-tree/chosen/power/max_current` | `5000`（3A 電源だと USB 給電が制限される） |
| 電圧低下・過熱 | `vcgencmd get_throttled` | `throttled=0x0` |
| ファン | `cat /sys/class/hwmon/hwmon*/fan1_input` | 0 より大きい回転数 |
| ページサイズ | `getconf PAGESIZE` | `16384`（4KB に切り替えた場合は `4096`。「8. 機体ごとの設定」に記録する） |
| 録音デバイス | `arecord -l` | USB PnP Audio Device が見える |
| 再生デバイス | `aplay -l`、`wpctl status` | 使うスピーカー（HDMI など）が Sinks にある |

## 4. プログラムの配置（PC から）

リポジトリのフォルダ（PC の Git Bash）で実行する。機体の SSH の別名を引数に渡す（省略時は `raspi-voice`）。

```bash
tools/deploy.sh raspi-voice
```

- 送るもの：`voice_assistant/`、`scripts/`、`tools/`、`requirements.txt`、`.env.example`（`__pycache__` は除く）。
- Pi 側の上記のものはいったん消してから送り直すため、PC で削除したファイルは Pi からも消える。
  `venv/`・`.env`・`models/`・`recordings/` には触らない。

## 5. 実行環境の準備（apt パッケージ・venv・Python パッケージ・.env のひな形）

```bash
ssh raspi-voice 'bash ~/voice-assistant/tools/setup_pi.sh'
```

- 何度実行してもよい。`requirements.txt` や `tools/apt-packages.txt` を変えたあとにも実行する。
- sudo にパスワードが必要な機体では `ssh -t` を付ける（2025-05-13 のイメージの初期ユーザーは不要だった）。
- スクリプトが行うこと（手作業で行う場合の手順）：
  1. `tools/apt-packages.txt` のうち未導入のものを `sudo apt-get install` する
  2. `~/voice-assistant/venv` がなければ `python3 -m venv venv` で作る
  3. `venv/bin/pip install -r requirements.txt`
  4. `.env` がなければ `.env.example` をコピーし、`chmod 600` にする

| apt パッケージ | 用途 | ライセンス |
|---|---|---|
| libportaudio2 | sounddevice（録音・再生）が使う | MIT 系（PortAudio License） |

- python3-venv・python3-pip は OS に最初から入っている（2025-05-13 のイメージで確認）。
- Raspberry Pi OS は `/etc/pip.conf` で piwheels（Pi 向けのビルド済みパッケージ）を参照する設定になっている。
- Python パッケージは `requirements.txt` のとおり、間接的な依存も含めて版を固定している
  （sounddevice：MIT、numpy：BSD-3-Clause ほか、python-dotenv：BSD-3-Clause、cffi：MIT-0、pycparser：BSD-3-Clause）。
  **固定した版が入手できない場合**は、`requirements.txt` の冒頭のコメントに従い、新しい版で確認し直す。

## 6. .env の記入（Pi 上。値はユーザーが自分で記入する）

```bash
nano ~/voice-assistant/.env
```

- `GEMINI_API_KEY`：Google AI Studio で発行したキー。
  **複数台で同じキー（同じプロジェクト）を使うと、無料枠の回数制限を全台で分け合う**ことになる。
- `AUDIO_INPUT_DEVICE` / `AUDIO_OUTPUT_DEVICE`：空なら既定のデバイス。機体ごとに変える場合に記入する。

## 7. モデルのダウンロード

（段階 2 で追加する。モデル名・入手先・サイズ・ライセンス・置き場所を記録し、ダウンロードは tools/setup_pi.sh に組み込む）

## 8. 機体ごとの設定

機体によって変わりうるもの。作り直すときは同じ値を設定し直す。

| 項目 | 設定場所 | 備考 |
|---|---|---|
| ホスト名・ユーザー名 | Imager | ― |
| SSH の別名 | PC の `~/.ssh/config` | ― |
| API キー・使用デバイス | Pi の `~/voice-assistant/.env` | ― |
| マイクの録音音量 | `alsamixer -c <マイクのカード番号>`（F4 で録音側） | 機体・マイクごとに調整 |
| 既定の出力先 | `wpctl status` / `wpctl set-default <番号>` | HDMI と USB スピーカーを両方つなぐ場合 |
| カーネルのページサイズ | `/boot/firmware/config.txt` | 標準（16KB）から変えた場合のみ記録する |

## 9. 動作確認

```bash
cd ~/voice-assistant
venv/bin/python scripts/00_audio_check.py --list
venv/bin/python scripts/00_audio_check.py
```

- `--list` で USB マイクと `default` が見えること。
- 録音中に話しかけ、再生された声が聞き取れること（耳で確認）。録音は `recordings/audio-check.wav` に残る。
- 確認できたら、PC から `ssh raspi-voice 'bash ~/voice-assistant/tools/env_report.sh'` を実行し、
  出力に確認した範囲と結果を書き足して [verified-environments.md](verified-environments.md) の末尾に追記する。

## 10. 自動起動

（段階 3 で追加する）

---

## 付録：PC の開発環境

リポジトリのフォルダで実行する（Python 3.11 で確認）。

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/Scripts/python -m pytest
```

- `requirements*.txt` の先頭の `# -*- coding: utf-8 -*-` は消さない。
  Windows の pip が日本語のコメントを cp932 として読んで失敗するのを防ぐため。
