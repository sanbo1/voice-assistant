"""音声アシスタントを起動する（Pi 上の ~/voice-assistant で `venv/bin/python -m voice_assistant`）。Ctrl+C で終了。"""

import logging
import sys

from .ai import AiError
from .ai.gemini import chat_client_from_config
from .assistant import Assistant
from .config import load_assistant_config, load_audio_config, load_env_file, load_gemini_config
from .conversation_log import ConversationLog


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_env_file()
    # 手動で起動したとき（端末から実行したとき）は、会話ログを画面にも表示する
    log = ConversationLog(echo=sys.stdout.isatty())
    try:
        # 優先のモデルと予備のモデルを順に使う。切り替えたときは会話ログの「状態」に書く
        ai = chat_client_from_config(load_gemini_config(), on_status=log.status)
        Assistant(ai, audio_config=load_audio_config(), log=log,
                  assistant_config=load_assistant_config()).run()
    except AiError as e:
        log.error(str(e))
        return 1
    except KeyboardInterrupt:
        log.status("終了しました")
    finally:
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
