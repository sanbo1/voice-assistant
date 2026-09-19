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

## 2026-09-19：段階 2 の手順 2（ウェイクワード検知）

- 結果：成功（しきい値 0.5）
  - `scripts/01_wakeword.py --show-scores` で「hey jarvis」を 5 回発話 → 4 回検知（スコア 0.83／0.76／0.85／0.51）
    - 検知しなかった 1 回は小声で話しかけたもの
    - スコア 0.51 の 1 回は「ジャービス」だけを発話したもの（しきい値ぎりぎりで反応）
  - 約 36 秒間、それ以外の会話・物音での誤検知なし
  - 処理時間：1 フレーム（80ms）あたり平均 8.6 ms（実時間の約 11%）
  - onnxruntime のテレメトリ無効化（`ORT_DISABLE_TELEMETRY=1`）後、テレメトリ用のファイルが作られないことを確認
  - PC（Windows 11、Python 3.11.9）で pytest 16 件成功
- 機体：Raspberry Pi 5 Model B Rev 1.1（メモリ 15.8 GiB）
- OS：Debian GNU/Linux 12 (bookworm)（イメージ：Raspberry Pi reference 2025-05-13）
- カーネル：6.12.34+rpt-rpi-2712（aarch64、ページサイズ 16384）
- Python：3.11.2（pip 23.0.1）
- 周辺機器：前回と同じ（USB マイク、HDMI モニターのスピーカー）。microSD は 2015 年製で書き込みが非常に遅い

apt パッケージ（tools/apt-packages.txt に載せているもの）：

```
libportaudio2=19.6.0-1.2
```

pip パッケージ（venv の pip freeze。このまま requirements として使える）：

```
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
cloudpickle==3.1.2
flatbuffers==25.12.19
idna==3.20
joblib==1.6.0
narwhals==2.26.0
numpy==2.4.6
onnxruntime==1.30.0
openwakeword==0.6.0
packaging==26.3
protobuf==7.36.2
pycparser==3.0
python-dotenv==1.2.3
requests==2.34.2
scikit-learn==1.9.1
scipy==1.17.1
sounddevice==0.5.6
tflite-runtime==2.14.0
threadpoolctl==3.7.0
tqdm==4.70.1
urllib3==2.8.0
```

モデル（tools/models.txt に載せているもの。SHA-256 の先頭 16 文字）：

```
models/openwakeword/melspectrogram.onnx  ba2b0e0f8b7b8753
models/openwakeword/embedding_model.onnx  70d164290c1d095d
models/openwakeword/hey_jarvis_v0.1.onnx  94a13cfe60075b13
```

## 2026-09-19：段階 2 の手順 3（録音と発話区間検出）、ウェイクワードのしきい値の見直し

- 結果：成功（ウェイクワードの反応率には課題が残る）
  - `scripts/02_record_utterance.py`：「hey jarvis」→ お知らせ音 → 質問 → 話し終わり（無音 1.0 秒）で停止 → 保存・再生
    - 発話 3 回：いずれも話し終わりで停止し、2.8〜3.3 秒の発話を切り出せた。ウェイクワード直後に続けて話しても録音できた
    - 無発話 1 回：5.0 秒で「時間内に話し始めなかった」として終了
  - Silero VAD の処理時間：1 フレーム（32ms）あたり約 0.3 ms。お知らせ音をマイクが拾っても声の確率は最大 0.34（発話と誤判定しない）
  - HDMI の音声出力の休止（WirePlumber の既定で 5 秒）から戻る際にモニターが消え、その間の再生音が失われる問題があった。
    HDMI の出力を休止させない設定（tools/pi-config/wireplumber/）で解消
  - ウェイクワード：しきい値 0.5 では取りこぼしが多かったため 0.35 に変更
    - しきい値 0.35 で 8 回発話 → 4 回検知（スコア 0.93／0.39／0.68／0.82）。取りこぼした回のスコアは 0.0〜0.32
    - しきい値 0.35 で約 11 分間（654 秒）、生活音の中で誤検知 0 回。処理時間 1 フレーム（80ms）あたり平均 10.7 ms
    - 同じ録音をスピーカーから流しても、スコアは 0.32〜0.89 とばらつく。取りこぼしの主因は、この発話者の言い方に対する
      モデル（hey_jarvis_v0.1）の認識の安定性と推測（設定変更・ノイズ・処理経路の異常ではないことを確認済み）
  - PC（Windows 11、Python 3.11.9）で pytest 35 件成功
- 機体：Raspberry Pi 5 Model B Rev 1.1（メモリ 15.8 GiB）
- OS：Debian GNU/Linux 12 (bookworm)（イメージ：Raspberry Pi reference 2025-05-13）
- カーネル：6.12.34+rpt-rpi-2712（aarch64、ページサイズ 16384）
- Python：3.11.2（pip 23.0.1）
- 周辺機器：前回と同じ（USB マイク、HDMI モニターのスピーカー）。WirePlumber 0.4.13、PipeWire 1.2.7

apt パッケージ（tools/apt-packages.txt に載せているもの）：

```
libportaudio2=19.6.0-1.2
```

pip パッケージ（venv の pip freeze。このまま requirements として使える）：

```
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
cloudpickle==3.1.2
flatbuffers==25.12.19
idna==3.20
joblib==1.6.0
narwhals==2.26.0
numpy==2.4.6
onnxruntime==1.30.0
openwakeword==0.6.0
packaging==26.3
protobuf==7.36.2
pycparser==3.0
python-dotenv==1.2.3
requests==2.34.2
scikit-learn==1.9.1
scipy==1.17.1
sounddevice==0.5.6
tflite-runtime==2.14.0
threadpoolctl==3.7.0
tqdm==4.70.1
urllib3==2.8.0
```

モデル（tools/models.txt に載せているもの。SHA-256 の先頭 16 文字）：

```
models/openwakeword/melspectrogram.onnx  ba2b0e0f8b7b8753
models/openwakeword/embedding_model.onnx  70d164290c1d095d
models/openwakeword/hey_jarvis_v0.1.onnx  94a13cfe60075b13
models/silero_vad/silero_vad.onnx  1a153a22f4509e29
```

## 2026-09-19：段階 2 の手順 4（音声認識：Vosk 小型モデル）

- 結果：成功（固有名詞などに誤認識あり）
  - vosk 0.3.45 の Pi 用ライブラリは、ページサイズ 16KB のカーネルで問題なく読み込めた
  - `scripts/03_transcribe.py --listen` で 6 回発話 → 完全一致 4 回（「五分後に教えて」の漢数字化を含む）
    - 誤認識：「今って令和何年」→「今て例は何年」、「日本で一番高い山はどこ」→「日本で一番高い山とこう」
  - 認識時間：2.5〜3.5 秒の発話に 1.6〜2.1 秒（話し終わってからまとめて認識した場合）。モデルの読み込み 0.7 秒
    - 話しながら少しずつ認識させると、話し終わりから結果までは 0.04 秒（同じ録音で確認）。段階 3 でこの方式にする予定
  - PC（Windows 11、Python 3.11.9）で pytest 39 件成功
- 機体：Raspberry Pi 5 Model B Rev 1.1（メモリ 15.8 GiB）
- OS：Debian GNU/Linux 12 (bookworm)（イメージ：Raspberry Pi reference 2025-05-13）
- カーネル：6.12.34+rpt-rpi-2712（aarch64、ページサイズ 16384）
- Python：3.11.2（pip 23.0.1）
- 周辺機器：前回と同じ（USB マイク、HDMI モニターのスピーカー）

apt パッケージ（tools/apt-packages.txt に載せているもの）：

```
libportaudio2=19.6.0-1.2
```

pip パッケージ（venv の pip freeze。このまま requirements として使える）：

```
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
cloudpickle==3.1.2
flatbuffers==25.12.19
idna==3.20
joblib==1.6.0
narwhals==2.26.0
numpy==2.4.6
onnxruntime==1.30.0
openwakeword==0.6.0
packaging==26.3
protobuf==7.36.2
pycparser==3.0
python-dotenv==1.2.3
requests==2.34.2
scikit-learn==1.9.1
scipy==1.17.1
sounddevice==0.5.6
srt==3.5.3
tflite-runtime==2.14.0
threadpoolctl==3.7.0
tqdm==4.70.1
urllib3==2.8.0
vosk==0.3.45
websockets==17.1
```

モデル（tools/models.txt に載せているもの。SHA-256 の先頭 16 文字）：

```
models/openwakeword/melspectrogram.onnx  ba2b0e0f8b7b8753
models/openwakeword/embedding_model.onnx  70d164290c1d095d
models/openwakeword/hey_jarvis_v0.1.onnx  94a13cfe60075b13
models/silero_vad/silero_vad.onnx  1a153a22f4509e29
models/vosk-model-small-ja-0.22.zip  efa092d280153a77
```

## 2026-09-19：段階 2 の手順 5（AI：Gemini API）

- 結果：成功
  - Gemini の REST API（generateContent）を requests で直接呼ぶ方式（公式 SDK は使わない。追加パッケージなし）
  - gemini-2.5-flash は新規利用者には提供終了（HTTP 404。API が gemini-3.6-flash を案内）。gemini-3.6-flash を採用
  - gemini-3.6-flash、思考 minimal、改善後のプロンプトで 6 回送信し、すべて期待どおり（応答 1.3〜2.0 秒）
    - 誤認識文「今て例は何年」→ 令和八年と回答、「日本で一番高い山とこう」→ 富士山と回答
    - 「五分後に教えて」→ タイマーはできないと回答（プロンプト改善前は「タイマーでお知らせします」と引き受けていた）
    - 「明日の東京の天気は」→ 最新情報は分からないと回答
    - 履歴あり：「富士山の高さは」→「それは何県にある？」で富士山の所在県を回答
  - 思考の既定（dynamic）では応答 3.0〜7.0 秒。minimal は 1.3〜3.3 秒で、答えの質に大きな差は見られなかった
  - 無料枠：約 25 秒間に 6 回送信したところで HTTP 429（回数の上限）
  - PC（Windows 11、Python 3.11.9）で pytest 56 件成功
- 機体：Raspberry Pi 5 Model B Rev 1.1（メモリ 15.8 GiB）
- OS：Debian GNU/Linux 12 (bookworm)（イメージ：Raspberry Pi reference 2025-05-13）
- カーネル：6.12.34+rpt-rpi-2712（aarch64、ページサイズ 16384）
- Python：3.11.2（pip 23.0.1）
- 周辺機器：前回と同じ（USB マイク、HDMI モニターのスピーカー）

apt パッケージ（tools/apt-packages.txt に載せているもの）：

```
libportaudio2=19.6.0-1.2
```

pip パッケージ（venv の pip freeze。このまま requirements として使える）：

```
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
cloudpickle==3.1.2
flatbuffers==25.12.19
idna==3.20
joblib==1.6.0
narwhals==2.26.0
numpy==2.4.6
onnxruntime==1.30.0
openwakeword==0.6.0
packaging==26.3
protobuf==7.36.2
pycparser==3.0
python-dotenv==1.2.3
requests==2.34.2
scikit-learn==1.9.1
scipy==1.17.1
sounddevice==0.5.6
srt==3.5.3
tflite-runtime==2.14.0
threadpoolctl==3.7.0
tqdm==4.70.1
urllib3==2.8.0
vosk==0.3.45
websockets==17.1
```

モデル（tools/models.txt に載せているもの。SHA-256 の先頭 16 文字）：

```
models/openwakeword/melspectrogram.onnx  ba2b0e0f8b7b8753
models/openwakeword/embedding_model.onnx  70d164290c1d095d
models/openwakeword/hey_jarvis_v0.1.onnx  94a13cfe60075b13
models/silero_vad/silero_vad.onnx  1a153a22f4509e29
models/vosk-model-small-ja-0.22.zip  efa092d280153a77
```

## 2026-09-19：段階 2 の手順 6（音声合成：Open JTalk）

- 結果：成功（声が少しこもって聞こえる点は改良の候補として残す）
  - `scripts/05_speak.py` で手順 5 の Gemini の返答 3 文を読み上げ。漢数字（二千二十六年、令和八年）と算用数字（3776メートル）は正しく読まれた
  - 合成時間：5.4〜8.1 秒の音声に 0.33〜0.48 秒（速さ 1.2 倍）。合成した WAV は標準出力で受け取り、ファイルに書かない
  - 聞き取りの確認（HDMI モニターのスピーカー）：イントネーション・区切りは問題なし。速さは 1.2 倍が自然（既定を 1.2 に）
  - 音量：合成直後は実効値 -22〜-24 dBFS と小さかったため、最大振幅 -1 dBFS に揃える処理を追加（実効値 -18 dBFS 前後）
  - 誤読：「お手数」を「おてかず」と読んだため、読み上げ前に置き換える表（READINGS）を追加し「おてすう」になることを確認
  - こもり：ポストフィルタ（-b）0.2〜0.6 を試したが改善せず、雑音が増えて音量も下がったため不採用（0.0 のまま）
  - PC（Windows 11、Python 3.11.9）で pytest 66 件成功
- 機体：Raspberry Pi 5 Model B Rev 1.1（メモリ 15.8 GiB）
- OS：Debian GNU/Linux 12 (bookworm)（イメージ：Raspberry Pi reference 2025-05-13）
- カーネル：6.12.34+rpt-rpi-2712（aarch64、ページサイズ 16384）
- Python：3.11.2（pip 23.0.1）
- 周辺機器：前回と同じ（USB マイク、HDMI モニターのスピーカー）

apt パッケージ（tools/apt-packages.txt に載せているもの）：

```
libportaudio2=19.6.0-1.2
open-jtalk=1.11-3
open-jtalk-mecab-naist-jdic=1.11-3
hts-voice-nitech-jp-atr503-m001=1.05-7
```

pip パッケージ（venv の pip freeze。このまま requirements として使える）：

```
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
cloudpickle==3.1.2
flatbuffers==25.12.19
idna==3.20
joblib==1.6.0
narwhals==2.26.0
numpy==2.4.6
onnxruntime==1.30.0
openwakeword==0.6.0
packaging==26.3
protobuf==7.36.2
pycparser==3.0
python-dotenv==1.2.3
requests==2.34.2
scikit-learn==1.9.1
scipy==1.17.1
sounddevice==0.5.6
srt==3.5.3
tflite-runtime==2.14.0
threadpoolctl==3.7.0
tqdm==4.70.1
urllib3==2.8.0
vosk==0.3.45
websockets==17.1
```

モデル（tools/models.txt に載せているもの。SHA-256 の先頭 16 文字）：

```
models/openwakeword/melspectrogram.onnx  ba2b0e0f8b7b8753
models/openwakeword/embedding_model.onnx  70d164290c1d095d
models/openwakeword/hey_jarvis_v0.1.onnx  94a13cfe60075b13
models/silero_vad/silero_vad.onnx  1a153a22f4509e29
models/vosk-model-small-ja-0.22.zip  efa092d280153a77
```

## 2026-09-19：段階 3（統合・会話ログの表示・自動起動）

- 結果：成功
  - `python -m voice_assistant`：ウェイクワード → お知らせ音 → 聞き取り（話しながら認識）→ Gemini（会話履歴つき）→ 読み上げ
    → 待ち受けの音 の流れを、利用者が話しかけて確認。続けての質問で前の話を踏まえた返答、無発話時の打ち切りも確認
  - 話しながら認識する方式：話し終わりの判定から認識結果まで 0.02〜0.04 秒（まとめて認識する方式と同じ結果を 4 件で確認）
  - 話し終わりの判定から読み上げ開始まで：1.56〜3.73 秒（認識 0.02〜0.04、AI 1.04〜2.14、合成 0.48〜1.56。
    合成 1.56 秒は再起動直後の 1 回目）。予備のモデルに切り替えた 1 回は 7.54 秒（AI 6.86 秒）
  - 会話ログ：デスクトップの「会話ログ」アイコンで表示（文字の大きさ 25、返答・エラーのあとに空行）
  - 画面が消えると HDMI のスピーカーから音が出ないことを確認 → 画面の自動消灯をオフ。11 分後も読み上げが聞こえることを確認
  - 自動起動（systemd のユーザーサービス＋linger）：モニターあり・モニターなしの両方で、電源を入れるだけで起動
    （モニターなしでも SSH 接続の 2 分以上前に起動。起動後 17 秒でサービス開始、モデル読み込みを含め約 21 秒で「起動しました」）。
    モニターなしでもデスクトップの自動ログインは行われていたため、linger だけで起動するかは未確認
  - Gemini：gemini-3.6-flash の無料枠が 1 日 20 回（GenerateRequestsPerDayPerProjectPerModel-FreeTier）と判明。
    予備のモデル（gemini-3.5-flash-lite → gemini-3.1-flash-lite）への自動切り替えを追加し、上限時に切り替わることを確認
  - 技術的なログは `journalctl _SYSTEMD_USER_UNIT=voice-assistant.service` で見る（`journalctl --user` では見られない）
  - PC（Windows 11、Python 3.11.9）で pytest 112 件成功
- 機体：Raspberry Pi 5 Model B Rev 1.1（メモリ 15.8 GiB）
- OS：Debian GNU/Linux 12 (bookworm)（イメージ：Raspberry Pi reference 2025-05-13）
- カーネル：6.12.34+rpt-rpi-2712（aarch64、ページサイズ 16384）
- Python：3.11.2（pip 23.0.1）
- 周辺機器・設定：USB マイク、HDMI モニター（ORION、1920×1080）のスピーカー。WirePlumber で HDMI の休止なし、
  画面の自動消灯オフ、linger 有効、デスクトップへの自動ログイン有効

apt パッケージ（tools/apt-packages.txt に載せているもの）：

```
libportaudio2=19.6.0-1.2
open-jtalk=1.11-3
open-jtalk-mecab-naist-jdic=1.11-3
hts-voice-nitech-jp-atr503-m001=1.05-7
```

pip パッケージ（venv の pip freeze。このまま requirements として使える）：

```
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
cloudpickle==3.1.2
flatbuffers==25.12.19
idna==3.20
joblib==1.6.0
narwhals==2.26.0
numpy==2.4.6
onnxruntime==1.30.0
openwakeword==0.6.0
packaging==26.3
protobuf==7.36.2
pycparser==3.0
python-dotenv==1.2.3
requests==2.34.2
scikit-learn==1.9.1
scipy==1.17.1
sounddevice==0.5.6
srt==3.5.3
tflite-runtime==2.14.0
threadpoolctl==3.7.0
tqdm==4.70.1
urllib3==2.8.0
vosk==0.3.45
websockets==17.1
```

モデル（tools/models.txt に載せているもの。SHA-256 の先頭 16 文字）：

```
models/openwakeword/melspectrogram.onnx  ba2b0e0f8b7b8753
models/openwakeword/embedding_model.onnx  70d164290c1d095d
models/openwakeword/hey_jarvis_v0.1.onnx  94a13cfe60075b13
models/silero_vad/silero_vad.onnx  1a153a22f4509e29
models/vosk-model-small-ja-0.22.zip  efa092d280153a77
```
