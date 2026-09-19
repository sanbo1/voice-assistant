"""音声認識の確認。WAV ファイル、またはその場で話した発話を文字にする。

使い方（Pi 上の ~/voice-assistant で）：
    venv/bin/python scripts/03_transcribe.py                          # recordings/utterance-*.wav を新しい順に 5 件
    venv/bin/python scripts/03_transcribe.py recordings/audio-check.wav
    venv/bin/python scripts/03_transcribe.py --listen                 # すぐに聞き取り、話し終わりで文字にする
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_assistant import audio  # noqa: E402
from voice_assistant.config import PROJECT_ROOT, load_audio_config, load_env_file  # noqa: E402
from voice_assistant.frames import rechunk  # noqa: E402
from voice_assistant.stt import VoskRecognizer  # noqa: E402
from voice_assistant.vad import EndpointConfig, Endpointer, SileroVad, collect_utterance  # noqa: E402
from voice_assistant.wav import read_wav  # noqa: E402


def transcribe_and_print(recognizer: VoskRecognizer, samples, sample_rate: int, label: str) -> None:
    start = time.perf_counter()
    text = recognizer.transcribe(samples, sample_rate)
    elapsed = time.perf_counter() - start
    seconds = len(samples) / sample_rate
    print(f"{label}（{seconds:.1f} 秒の音声、認識 {elapsed:.2f} 秒）")
    print(f"  →「{text}」" if text else "  →（聞き取れませんでした）")


def main() -> int:
    parser = argparse.ArgumentParser(description="音声認識の確認")
    parser.add_argument("wavs", nargs="*", type=Path, help="文字にする WAV（16kHz・16bit・モノラル）")
    parser.add_argument("--listen", action="store_true", help="マイクで聞き取った発話を文字にする")
    args = parser.parse_args()

    start = time.perf_counter()
    recognizer = VoskRecognizer()
    print(f"モデルの読み込み：{time.perf_counter() - start:.1f} 秒")

    if args.listen:
        load_env_file()
        config = load_audio_config()
        vad = SileroVad()
        frame_seconds = SileroVad.FRAME_SAMPLES / audio.SAMPLE_RATE
        stream = audio.stream_frames(SileroVad.FRAME_SAMPLES, device=config.input_device)
        print("話してください…")
        try:
            utterance = collect_utterance(
                rechunk(stream, SileroVad.FRAME_SAMPLES),
                vad.speech_probability,
                Endpointer(EndpointConfig(), frame_seconds),
            )
        except KeyboardInterrupt:
            print("\n中断しました")
            return 1
        finally:
            stream.close()
        if utterance.samples is None:
            print(f"聞き取り終了：{utterance.reason.value}")
            return 0
        transcribe_and_print(recognizer, utterance.samples, audio.SAMPLE_RATE, "聞き取った発話")
        return 0

    wavs = args.wavs or sorted((PROJECT_ROOT / "recordings").glob("utterance-*.wav"), reverse=True)[:5]
    if not wavs:
        print("文字にする WAV がありません")
        return 1
    for path in wavs:
        samples, sample_rate = read_wav(path)
        if samples.ndim != 1:
            print(f"{path.name}：モノラルの WAV のみ対応しています")
            continue
        transcribe_and_print(recognizer, samples, sample_rate, path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
