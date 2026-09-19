# voice-assistant

Raspberry Pi 5（16GB）で動作する音声AIアシスタント。
ウェイクワード検知 → 音声認識 → AI応答 → 読み上げ。構成と決定事項は `docs/design.md` を参照。

## 開発環境
- 開発：Windows PC 上の Claude Code。実行環境：Raspberry Pi（SSH の別名 `raspi-voice`）
- 言語：Python 3（Pi 上の venv で実行）
- 配置：開発中は `tools/deploy.sh <SSH の別名>` で Pi の `~/voice-assistant/` へコピーする（git 経由では配置しない）。
  Pi 側の準備（apt・venv・pip）は `tools/setup_pi.sh` で行う
- 接続先の IP アドレス・ユーザー名はリポジトリに書かない（`~/.ssh/config` の別名のみ使う）

## 環境の記録
- Pi に入れるもの（apt・pip・モデル）やシステム設定を変えたら、同じ変更の中で `docs/setup.md` を更新する。
- 動作確認の節目（段階の完了時、パッケージや OS を変えて動作確認したとき）には、
  `tools/env_report.sh` の出力と確認結果を `docs/verified-environments.md` に追記する。
- `docs/verified-environments.md` の過去の記録は消したり書き換えたりしない。
  OS や版を新しくしても、古い環境の記録として残す。

## 参照可能な外部パス
- `raspi-voice:~/voice-assistant/` … 配置先・実行場所。読み書き可。
- `raspi-voice` 上での参照系コマンド（ls, cat, arecord -l, python の実行など）は確認不要。
  パッケージのインストール（apt, pip）、システム設定の変更、`~/voice-assistant/` 外への書き込みは事前に確認する。

## テスト
- 音声入出力に依存しないロジック（AI 呼び出しの整形、会話履歴など）は pytest で単体テストを書き、PC 上で実行する。
- 音声を扱う部分は Pi 上でスクリプトを実行して確認する。聞き取り・発話の品質など、
  人が耳で確認する必要がある点は、確認手順を明記してユーザーに依頼する。

## 秘密情報
- API キーは Pi 上の `~/voice-assistant/.env` にのみ置き、ユーザーが自分で記入する。
  リポジトリには `.env.example`（値は空）のみを含める。
- `.env`、venv、音声認識モデルのファイル、録音データはコミットしない。
