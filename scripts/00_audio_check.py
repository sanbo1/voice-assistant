"""録音と再生の確認。数秒録音して音量を表示し、WAV に保存してから再生する。

使い方（Pi 上の ~/voice-assistant で）：
    venv/bin/python scripts/00_audio_check.py            # 5 秒録音して再生
    venv/bin/python scripts/00_audio_check.py --list     # デバイス一覧を表示するだけ
    venv/bin/python scripts/00_audio_check.py --seconds 3 --no-play
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_assistant import audio  # noqa: E402
from voice_assistant.config import PROJECT_ROOT, load_audio_config, load_env_file  # noqa: E402
from voice_assistant.levels import peak_dbfs, rms_dbfs  # noqa: E402
from voice_assistant.wav import write_wav  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="録音と再生の確認")
    parser.add_argument("--list", action="store_true", help="デバイス一覧を表示して終わる")
    parser.add_argument("--seconds", type=float, default=5.0, help="録音する秒数（既定：5）")
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "recordings" / "audio-check.wav",
        help="保存先の WAV（既定：recordings/audio-check.wav）",
    )
    parser.add_argument("--no-play", action="store_true", help="再生しない")
    args = parser.parse_args()

    if args.list:
        print(audio.list_devices())
        return 0

    load_env_file()
    config = load_audio_config()
    print(f"入力デバイス：{config.input_device or '既定'}／出力デバイス：{config.output_device or '既定'}")

    print(f"{args.seconds:g} 秒録音します。話しかけてください…")
    samples = audio.record(args.seconds, device=config.input_device)
    print(f"録音終了：ピーク {peak_dbfs(samples):.1f} dBFS／実効値 {rms_dbfs(samples):.1f} dBFS")

    write_wav(args.out, samples, audio.SAMPLE_RATE)
    print(f"保存しました：{args.out}")

    if not args.no_play:
        print("再生します…")
        audio.play(samples, audio.SAMPLE_RATE, device=config.output_device)
        print("再生終了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
