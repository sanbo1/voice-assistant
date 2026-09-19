"""ウェイクワード検知の確認。マイクの音声を流し続け、検知したら表示する。Ctrl+C で終了。

使い方（Pi 上の ~/voice-assistant で）：
    venv/bin/python scripts/01_wakeword.py                 # 「hey jarvis」を検知したら表示
    venv/bin/python scripts/01_wakeword.py --show-scores   # 約 1 秒ごとに最大スコアも表示（しきい値の調整用）
    venv/bin/python scripts/01_wakeword.py --threshold 0.6
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_assistant import audio  # noqa: E402
from voice_assistant.config import load_audio_config, load_env_file  # noqa: E402
from voice_assistant.wakeword import DEFAULT_MODEL, FRAME_SAMPLES, WakeWordDetector  # noqa: E402

FRAMES_PER_SECOND = audio.SAMPLE_RATE // FRAME_SAMPLES  # 12（1 フレーム 80ms）


def main() -> int:
    parser = argparse.ArgumentParser(description="ウェイクワード検知の確認")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="ウェイクワードのモデル（.onnx）")
    parser.add_argument("--threshold", type=float, default=0.5, help="検知のしきい値 0〜1（既定：0.5）")
    parser.add_argument("--show-scores", action="store_true", help="約 1 秒ごとに最大スコアを表示する")
    args = parser.parse_args()

    load_env_file()
    config = load_audio_config()
    detector = WakeWordDetector(args.model, threshold=args.threshold)
    print(f"モデル：{detector.name}／しきい値：{args.threshold}／入力デバイス：{config.input_device or '既定'}")
    print("「hey jarvis」と話しかけてください（Ctrl+C で終了）")

    detections = 0
    frames = 0
    busy_seconds = 0.0
    peak = 0.0
    try:
        for frame in audio.stream_frames(FRAME_SAMPLES, device=config.input_device):
            start = time.perf_counter()
            detected = detector.process(frame)
            busy_seconds += time.perf_counter() - start
            frames += 1

            if detected:
                detections += 1
                now = datetime.now().strftime("%H:%M:%S")
                print(f"[{now}] 検知しました（{detections} 回目、スコア {detector.last_score:.2f}）")

            if args.show_scores:
                peak = max(peak, detector.last_score)
                if frames % FRAMES_PER_SECOND == 0:
                    print(f"  最大スコア {peak:.2f}")
                    peak = 0.0
    except KeyboardInterrupt:
        pass

    if frames:
        average_ms = busy_seconds / frames * 1000
        print(f"\n終了：{frames / FRAMES_PER_SECOND:.0f} 秒間で {detections} 回検知。"
              f"処理時間は 1 フレーム（80ms）あたり平均 {average_ms:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
