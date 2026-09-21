"""ウェイクワード検知の確認。マイクの音声を流し続け、検知したら表示する。Ctrl+C で終了。

使い方（Pi 上の ~/voice-assistant で）：
    venv/bin/python scripts/01_wakeword.py                 # 「hey jarvis」を検知したら表示
    venv/bin/python scripts/01_wakeword.py --show-scores   # 約 1 秒ごとに最大スコアも表示（しきい値の調整用）
    venv/bin/python scripts/01_wakeword.py --threshold 0.5
    venv/bin/python scripts/01_wakeword.py --confirm-threshold 0.6   # 確認窓の最大スコアで見送る

指定しなかった調整値は .env（WAKEWORD_*）の設定を使う。
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_assistant import audio  # noqa: E402
from voice_assistant.config import (  # noqa: E402
    WakeWordConfig,
    load_audio_config,
    load_env_file,
    load_wakeword_config,
)
from voice_assistant.wakeword import DEFAULT_MODEL, FRAME_SAMPLES, WakeWordDetector  # noqa: E402

FRAMES_PER_SECOND = audio.SAMPLE_RATE // FRAME_SAMPLES  # 12（1 フレーム 80ms）


def main() -> int:
    load_env_file()
    defaults = load_wakeword_config()

    parser = argparse.ArgumentParser(description="ウェイクワード検知の確認")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="ウェイクワードのモデル（.onnx）")
    parser.add_argument("--threshold", type=float, default=defaults.threshold,
                        help="検知のしきい値 0〜1（既定：%(default)s）")
    parser.add_argument("--patience", type=int, default=defaults.patience_frames,
                        help="何フレーム続けてしきい値を超えたら確認窓に進むか。1 フレーム 80ms（既定：%(default)s）")
    parser.add_argument("--confirm-frames", type=int, default=defaults.confirm_frames,
                        help="立ち上がりのあと、何フレームぶん見てから決めるか（既定：%(default)s）")
    parser.add_argument("--confirm-threshold", type=float, default=defaults.confirm_threshold,
                        help="最大スコアがこの値未満なら反応しない。0 なら見送らない（既定：%(default)s）")
    parser.add_argument("--show-scores", action="store_true", help="約 1 秒ごとに最大スコアを表示する")
    args = parser.parse_args()

    config = load_audio_config()
    wakeword = WakeWordConfig(threshold=args.threshold, patience_frames=args.patience,
                              confirm_frames=args.confirm_frames, confirm_threshold=args.confirm_threshold)
    detector = WakeWordDetector(args.model, config=wakeword)
    print(f"モデル：{detector.name}／しきい値：{wakeword.threshold}／連続 {wakeword.patience_frames} フレーム"
          f"／確認窓 {wakeword.confirm_frames} フレーム（最大 {wakeword.confirm_threshold} 以上で反応）"
          f"／入力デバイス：{config.input_device or '既定'}")
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
                scores = " ".join(f"{score:.2f}" for score in detector.last_scores)
                print(f"[{now}] 検知しました（{detections} 回目、最大 {detector.last_peak:.2f}、"
                      f"並び {scores}、見送り {detector.last_suppressed} 回）")

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
