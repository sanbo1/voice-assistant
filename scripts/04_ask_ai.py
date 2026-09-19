"""AI（Gemini）の呼び出しの確認。質問の文章を送り、返答とかかった時間を表示する。

使い方（Pi 上の ~/voice-assistant で。.env に GEMINI_API_KEY が必要）：
    venv/bin/python scripts/04_ask_ai.py                        # 用意した質問（誤認識の例を含む）を順に送る
    venv/bin/python scripts/04_ask_ai.py "日本で一番高い山は"
    venv/bin/python scripts/04_ask_ai.py --keep-history "富士山の高さは" "それは何県にある？"
    venv/bin/python scripts/04_ask_ai.py --model gemini-3.6-flash --thinking-level minimal
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_assistant.ai import AiError, Message  # noqa: E402
from voice_assistant.ai.gemini import DEFAULT_MODEL, DEFAULT_THINKING_LEVEL, GeminiClient  # noqa: E402
from voice_assistant.config import load_env_file, load_gemini_config  # noqa: E402

# 手順 4 で実際に起きた誤認識（カッコ内が実際の発話）を含める
DEFAULT_QUESTIONS = [
    "今て例は何年",  # （今って令和何年）
    "日本で一番高い山とこう",  # （日本で一番高い山はどこ）
    "五分後に教えて",
    "明日の東京の天気は",
]
# 用意した質問を続けて送ると、無料枠の 1 分あたりの回数制限にかかることがあるため、間を空ける
INTERVAL_SECONDS = 5


def main() -> int:
    parser = argparse.ArgumentParser(description="AI（Gemini）の呼び出しの確認")
    parser.add_argument("questions", nargs="*", help="送る質問（省略時は用意した質問）")
    parser.add_argument("--model", help=f"使うモデル（省略時は .env の GEMINI_MODEL、なければ {DEFAULT_MODEL}）")
    parser.add_argument("--thinking-budget", type=int, help="思考に使うトークン数の上限（Gemini 2.5 系。0 で思考しない）")
    parser.add_argument("--thinking-level", help="思考の量（Gemini 3 系。minimal・low・medium・high。モデルにより異なる）")
    parser.add_argument("--keep-history", action="store_true", help="前の質問と返答を踏まえて次の質問を送る")
    args = parser.parse_args()

    load_env_file()
    config = load_gemini_config()
    model = args.model or config.model or DEFAULT_MODEL
    thinking_level = args.thinking_level or config.thinking_level
    if thinking_level is None and args.thinking_budget is None and model == DEFAULT_MODEL:
        thinking_level = DEFAULT_THINKING_LEVEL
    try:
        client = GeminiClient(config.api_key, model, thinking_budget=args.thinking_budget,
                              thinking_level=thinking_level)
    except AiError as e:
        print(f"エラー：{e}")
        return 1
    thinking = [f"budget={args.thinking_budget}"] if args.thinking_budget is not None else []
    thinking += [f"level={thinking_level}"] if thinking_level else []
    print(f"モデル：{model}／思考：{'、'.join(thinking) or '既定'}")

    history: list[Message] = []
    failures = 0
    for i, question in enumerate(args.questions or DEFAULT_QUESTIONS):
        if i > 0:
            time.sleep(INTERVAL_SECONDS)
        print(f"\n質問：{question}")
        start = time.perf_counter()
        try:
            answer = client.reply(question, history if args.keep_history else ())
        except AiError as e:
            print(f"  エラー（{time.perf_counter() - start:.2f} 秒）：{e}")
            failures += 1
            if e.status is not None and 400 <= e.status < 500 and e.status != 429:
                print("設定の誤りなど、繰り返しても直らないエラーのため中止します")
                break
            continue
        print(f"  返答（{time.perf_counter() - start:.2f} 秒）：{answer}")
        history += [Message("user", question), Message("assistant", answer)]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
