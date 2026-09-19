# 動作確認の履歴

どの環境（OS・パッケージの版）で何が動いたかの記録。過去の環境を作り直すときの手がかりにする。

## 記録のルール
- 動作確認の節目（段階の完了時、パッケージや OS を変えて動作確認したとき）に、**末尾に 1 節追記する**。
- 環境の部分は Pi 上で `tools/env_report.sh` を実行した出力を貼り、「確認した範囲」と「結果」を埋める。
- **過去の節は消したり書き換えたりしない**（OS や版を新しくしても、古い環境の記録として残す）。
  誤りを見つけた場合は、その節の末尾に「訂正（日付）：…」を追記する。
- 過去の環境を作り直すときは、その節の apt・pip の版を指定して入れる
  （pip は節の一覧をファイルに保存して `venv/bin/pip install -r <ファイル>` とする）。
- ユーザー名・ホスト名・IP アドレス・API キーは書かない。

---

## 2026-09-19：段階 1（接続確認）、段階 2 の手順 1（録音・再生の土台）

- 結果：成功
  - `scripts/00_audio_check.py --list` で USB マイクと `default`（PipeWire）を認識
  - `scripts/00_audio_check.py` で 5 秒録音 → WAV 保存 → HDMI モニターのスピーカーで再生。
    耳で聞いて問題なし（話したときの録音レベル：ピーク -8.7 dBFS／実効値 -30.0 dBFS）
  - `audio.stream_frames(1280)` で 16kHz・int16 のフレームを取得できる
  - PC（Windows 11、Python 3.11.9、`requirements.txt` + `requirements-dev.txt`）で pytest 12 件成功
- 機体：Raspberry Pi 5 Model B Rev 1.1（メモリ 15.8 GiB）
- OS：Debian GNU/Linux 12 (bookworm)（イメージ：Raspberry Pi reference 2025-05-13）
- カーネル：6.12.34+rpt-rpi-2712（aarch64、ページサイズ 16384）
- Python：3.11.2（pip 23.0.1）
- 周辺機器：USB マイク（C-Media 製 USB PnP Audio Device）、HDMI モニターのスピーカー、電源 5V/5A、ファン付き

apt パッケージ（tools/apt-packages.txt に載せているもの）：

```
libportaudio2=19.6.0-1.2
```

pip パッケージ（venv の pip freeze。このまま requirements として使える）：

```
cffi==2.1.1
numpy==2.4.6
pycparser==3.0
python-dotenv==1.2.3
sounddevice==0.5.6
```
