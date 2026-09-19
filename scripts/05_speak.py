"""音声合成の確認。文章を Open JTalk で読み上げ、合成にかかった時間を表示する。

使い方（Pi 上の ~/voice-assistant で）：
    venv/bin/python scripts/05_speak.py                       # 用意した文章（手順 5 の Gemini の返答）を読み上げる
    venv/bin/python scripts/05_speak.py "こんにちは。今日はいい天気ですね。"
    venv/bin/python scripts/05_speak.py --speed 1.0
    venv/bin/python scripts/05_speak.py --compare              # ポストフィルタ 0.0／0.2／0.4／0.6 を聞き比べる
    venv/bin/python scripts/05_speak.py --postfilter 0.4
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_assistant import audio  # noqa: E402
from voice_assistant.config import load_audio_config, load_env_file  # noqa: E402
from voice_assistant.tts import DEFAULT_SPEED, OpenJTalk, to_speakable  # noqa: E402

# 手順 5 で Gemini が実際に返した文章（漢数字と算用数字が混ざっている）
DEFAULT_TEXTS = [
    "現在は、西暦二千二十六年です。和暦では令和八年になりますよ。",
    "富士山の高さは、標高3776メートルです。日本で一番高い山として知られていますね。",
    "すみません、私にはタイマーやアラームの設定ができません。お手数ですが、スマートフォンなどのタイマー機能をご利用ください。",
]
# --compare で聞き比べるポストフィルタの値
COMPARE_POSTFILTERS = [0.0, 0.2, 0.4, 0.6]


def main() -> int:
    parser = argparse.ArgumentParser(description="音声合成の確認")
    parser.add_argument("texts", nargs="*", help="読み上げる文章（省略時は用意した文章）")
    parser.add_argument("--speed", type=float, default=DEFAULT_SPEED, help="話す速さ（既定：%(default)s）")
    parser.add_argument("--postfilter", type=float, default=0.0, help="ポストフィルタ 0〜1（既定：%(default)s）")
    parser.add_argument("--all-pass", type=float, help="オールパス定数 0〜1（省略時は声のデータの既定値）")
    parser.add_argument("--compare", action="store_true", help="ポストフィルタを変えた音声を順に再生して聞き比べる")
    parser.add_argument("--no-play", action="store_true", help="再生しない（合成時間だけ測る）")
    args = parser.parse_args()

    load_env_file()
    config = load_audio_config()

    if args.compare:
        text = args.texts[0] if args.texts else DEFAULT_TEXTS[1]
        for postfilter in COMPARE_POSTFILTERS:
            samples, sample_rate = OpenJTalk(speed=args.speed, postfilter=postfilter).synthesize(to_speakable(text))
            print(f"ポストフィルタ {postfilter}")
            audio.play(samples, sample_rate, device=config.output_device)
            time.sleep(1.0)
        return 0

    tts = OpenJTalk(speed=args.speed, postfilter=args.postfilter, all_pass=args.all_pass)

    for text in args.texts or DEFAULT_TEXTS:
        speakable = to_speakable(text)
        start = time.perf_counter()
        samples, sample_rate = tts.synthesize(speakable)
        elapsed = time.perf_counter() - start
        print(f"「{speakable}」")
        print(f"  合成 {elapsed:.2f} 秒（音声 {len(samples) / sample_rate:.1f} 秒、{sample_rate} Hz）")
        if not args.no_play:
            audio.play(samples, sample_rate, device=config.output_device)
    return 0


if __name__ == "__main__":
    sys.exit(main())
