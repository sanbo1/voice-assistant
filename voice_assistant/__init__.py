"""Raspberry Pi 上で動く音声AIアシスタント。"""

import os

# onnxruntime の公式ビルドは Linux でも Microsoft へのテレメトリ送信が既定で有効になっている。
# onnxruntime を読み込む前に設定する必要があるため、パッケージの最初で無効にする。
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
