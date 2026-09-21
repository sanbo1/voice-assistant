"""録音と発話区間検出の確認。ウェイクワードのあとに話した内容を、話し終わりまで録音して保存・再生する。

使い方（Pi 上の ~/voice-assistant で）：
    venv/bin/python scripts/02_record_utterance.py                  # 「hey jarvis」のあとに話す
    venv/bin/python scripts/02_record_utterance.py --no-wakeword    # すぐに聞き取りを始める
    venv/bin/python scripts/02_record_utterance.py --end-silence 0.8 --show-probs
    venv/bin/python scripts/02_record_utterance.py --show-scores    # 反応しないときの調査用
"""

import argparse
import dataclasses
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_assistant import audio  # noqa: E402
from voice_assistant.config import (  # noqa: E402
    PROJECT_ROOT,
    load_audio_config,
    load_env_file,
    load_wakeword_config,
)
from voice_assistant.frames import rechunk  # noqa: E402
from voice_assistant.levels import rms_dbfs  # noqa: E402
from voice_assistant.sounds import wake_chime  # noqa: E402
from voice_assistant.vad import EndpointConfig, Endpointer, SileroVad, collect_utterance  # noqa: E402
from voice_assistant.wakeword import FRAME_SAMPLES, WakeWordDetector  # noqa: E402
from voice_assistant.wav import write_wav  # noqa: E402


def main() -> int:
    load_env_file()
    defaults = EndpointConfig()
    wakeword_defaults = load_wakeword_config()
    parser = argparse.ArgumentParser(description="録音と発話区間検出の確認")
    parser.add_argument("--no-wakeword", action="store_true", help="ウェイクワードを待たずに聞き取りを始める")
    parser.add_argument("--wake-threshold", type=float, default=wakeword_defaults.threshold,
                        help="ウェイクワード検知のしきい値 0〜1（既定：%(default)s）")
    parser.add_argument("--threshold", type=float, default=defaults.threshold,
                        help="発話区間の判定で声とみなす確率（既定：%(default)s）")
    parser.add_argument("--end-silence", type=float, default=defaults.end_silence_seconds,
                        help="話し終わりとみなす無音の秒数（既定：%(default)s）")
    parser.add_argument("--show-scores", action="store_true",
                        help="ウェイクワードを待っている間、1 秒ごとにマイクの音量と最大スコアを表示する")
    parser.add_argument("--show-probs", action="store_true", help="聞き取り中、約 0.1 秒ごとに声の確率を表示する")
    parser.add_argument("--no-play", action="store_true", help="録音した発話を再生しない")
    parser.add_argument("--no-chime", action="store_true", help="ウェイクワード検知時にお知らせ音を鳴らさない")
    args = parser.parse_args()

    config = load_audio_config()
    endpoint_config = EndpointConfig(threshold=args.threshold, end_silence_seconds=args.end_silence)
    vad = SileroVad()
    wakeword = dataclasses.replace(wakeword_defaults, threshold=args.wake_threshold)
    detector = None if args.no_wakeword else WakeWordDetector(config=wakeword)
    chime = wake_chime(audio.SAMPLE_RATE)

    stream = audio.stream_frames(FRAME_SAMPLES, device=config.input_device)
    try:
        if detector is not None:
            print("「hey jarvis」と話しかけてください（Ctrl+C で終了）")
            recent: list = []
            peak_score = 0.0
            for frame in stream:
                detected = detector.process(frame)
                if args.show_scores:
                    recent.append(frame)
                    peak_score = max(peak_score, detector.last_score)
                    if len(recent) == audio.SAMPLE_RATE // FRAME_SAMPLES:
                        print(f"  音量 {rms_dbfs(np.concatenate(recent)):6.1f} dBFS  最大スコア {peak_score:.2f}")
                        recent.clear()
                        peak_score = 0.0
                if detected:
                    if not args.no_chime:
                        audio.play_nowait(chime, audio.SAMPLE_RATE, device=config.output_device)
                    print(f"ウェイクワードを検知しました（スコア {detector.last_score:.2f}）")
                    break

        print("聞き取り中…話してください")
        frame_seconds = SileroVad.FRAME_SAMPLES / audio.SAMPLE_RATE
        count = 0

        def speech_probability(frame):
            nonlocal count
            prob = vad.speech_probability(frame)
            count += 1
            if args.show_probs and count % 3 == 0:
                print(f"  {count * frame_seconds:5.1f} 秒  確率 {prob:.2f}  {'■' * round(prob * 20)}")
            return prob

        vad.reset()
        utterance = collect_utterance(
            rechunk(stream, SileroVad.FRAME_SAMPLES),
            speech_probability,
            Endpointer(endpoint_config, frame_seconds),
        )
    except KeyboardInterrupt:
        print("\n中断しました")
        return 1
    finally:
        stream.close()  # マイクの入力を止める

    print(f"聞き取り終了：{utterance.reason.value}（聞き取り開始から {count * frame_seconds:.1f} 秒）")
    if utterance.samples is None:
        return 0

    seconds = len(utterance.samples) / audio.SAMPLE_RATE
    print(f"発話：{seconds:.1f} 秒／実効値 {rms_dbfs(utterance.samples):.1f} dBFS")
    out = PROJECT_ROOT / "recordings" / f"utterance-{datetime.now():%Y%m%d-%H%M%S}.wav"
    write_wav(out, utterance.samples, audio.SAMPLE_RATE)
    print(f"保存しました：{out}")

    if not args.no_play:
        print("再生します…")
        audio.play(utterance.samples, audio.SAMPLE_RATE, device=config.output_device)
    return 0


if __name__ == "__main__":
    sys.exit(main())
