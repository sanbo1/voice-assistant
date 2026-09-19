import re

from voice_assistant.conversation_log import ConversationLog


def read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_writes_labeled_lines_with_time(tmp_path):
    path = tmp_path / "logs" / "conversation.log"
    log = ConversationLog(path)
    log.status("起動しました")
    log.heard("日本で一番高い山は")
    log.reply("富士山です。\n標高は3776メートルです。")
    log.error("利用回数の上限に達しました")
    log.close()

    lines = read_lines(path)
    assert len(lines) == 4
    assert all(re.match(r"^\d{2}/\d{2} \d{2}:\d{2}:\d{2}  ", line) for line in lines)
    assert lines[0].endswith("状態：起動しました")
    assert lines[1].endswith("聞き取り：日本で一番高い山は")
    # 改行は 1 行にまとめる（ターミナルで 1 件が 1 行になるように）
    assert lines[2].endswith("返答：富士山です。 標高は3776メートルです。")
    assert lines[3].endswith("エラー：利用回数の上限に達しました")


def test_empty_heard_text(tmp_path):
    path = tmp_path / "conversation.log"
    log = ConversationLog(path)
    log.heard("")
    log.close()
    assert read_lines(path)[0].endswith("聞き取り：（聞き取れませんでした）")


def test_two_logs_do_not_mix(tmp_path):
    a = ConversationLog(tmp_path / "a.log")
    b = ConversationLog(tmp_path / "b.log")
    a.status("A")
    b.status("B")
    a.close()
    b.close()
    assert read_lines(tmp_path / "a.log")[0].endswith("状態：A")
    assert read_lines(tmp_path / "b.log")[0].endswith("状態：B")


def test_reply_with_model_label(tmp_path):
    path = tmp_path / "conversation.log"
    log = ConversationLog(path)
    log.reply("琵琶湖です。", model="gemini-3.5-flash-lite")
    log.close()
    assert read_lines(path)[0].endswith("返答（gemini-3.5-flash-lite）：琵琶湖です。")
