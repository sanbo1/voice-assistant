import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.display_log import (  # noqa: E402
    Statistics,
    confidence_mark,
    current_state,
    latest_exchange,
    parse_line,
    past_exchanges,
    read_entries,
    statistics,
)


def test_parse_heard_with_confidence():
    entry = parse_line("09/23 14:30:00  聞き取り（確信度 0.92）：今日は何の日")
    assert (entry.kind, entry.body, entry.confidence) == ("heard", "今日は何の日", 0.92)
    assert entry.clock == "14:30"


def test_parse_heard_without_confidence():
    """確信度を記録する前の行も読める。"""
    entry = parse_line("09/20 10:00:00  聞き取り：今日の天気")
    assert (entry.kind, entry.confidence) == ("heard", None)


def test_parse_reply_with_fallback_model():
    entry = parse_line("09/23 14:30:05  返答（gemini-3.5-flash-lite）：秋分の日です。")
    assert (entry.kind, entry.model, entry.body) == ("reply", "gemini-3.5-flash-lite", "秋分の日です。")


def test_parse_reply_keeps_colons_in_body():
    """本文に「：」が入っていても切らない。"""
    entry = parse_line("09/23 14:30:05  返答：時刻は 14：30 です。")
    assert entry.body == "時刻は 14：30 です。"


def test_parse_status_and_error():
    assert parse_line("09/23 14:29:00  状態：ウェイクワードを待っています（…）").kind == "status"
    assert parse_line("09/23 14:29:00  エラー：接続できません").kind == "error"


def test_parse_broken_line():
    assert parse_line("これはログの形ではない") is None
    assert parse_line("") is None


LOG = """09/23 14:20:00  状態：起動しました
09/23 14:20:05  状態：ウェイクワードを待っています（「hey jarvis」と話しかけてください）
09/23 14:21:00  聞き取り（確信度 0.95）：富士山の高さは
09/23 14:21:03  返答：3776メートルです。
09/23 14:22:00  状態：ウェイクワードは空振りでした（聞き取りが短い、最大 0.48、並び …）
09/23 14:23:00  聞き取り（確信度 0.40）：ん他のそして秀吉
09/23 14:23:00  状態：雑音とみなして AI に送りませんでした
09/23 14:24:00  聞き取り（確信度 0.91）：今日は何の日
09/23 14:24:04  返答：秋分の日です。
09/23 14:24:05  状態：応答に時間がかかりました（合計 5.2 秒…）
09/23 14:25:00  聞き取り（確信度 0.70）：明日の天気は
09/23 14:25:03  返答（gemini-3.5-flash-lite）：分かりません。
"""


def entries():
    from tools.display_log import parse_line as parse

    return [e for line in LOG.splitlines() if (e := parse(line)) is not None]


def test_latest_exchange():
    heard, reply = latest_exchange(entries())
    assert heard.body == "明日の天気は"
    assert reply.body == "分かりません。"


def test_exchange_without_reply_is_kept():
    """雑音として弾かれた回は、聞き取りだけが残る（何と聞こえたかを画面に出すため）。"""
    log = "\n".join(LOG.splitlines()[:7])
    found = [e for line in log.splitlines() if (e := parse_line(line)) is not None]
    heard, reply = latest_exchange(found)
    assert heard.body == "ん他のそして秀吉"
    assert reply is None


def test_past_exchanges_are_newest_first_and_complete():
    past = past_exchanges(entries())
    # 直近（明日の天気は）は含まず、返答のある回だけが新しい順に並ぶ
    assert [heard.body for heard, _ in past] == ["今日は何の日", "富士山の高さは"]


def test_past_exchanges_limit():
    assert len(past_exchanges(entries(), limit=1)) == 1


def test_latest_exchange_when_empty():
    assert latest_exchange([]) is None


def test_confidence_mark():
    assert confidence_mark(0.92)[0] == "○"
    assert confidence_mark(0.70)[0] == "△"
    assert confidence_mark(0.40)[0] == "×"
    assert "近くで話してみてください" in confidence_mark(0.40)[1]
    assert confidence_mark(None) == ("", "")


def test_current_state_from_status():
    assert current_state(entries()[:2]) == "waiting"


def test_current_state_after_heard_and_reply():
    """聞き取りの直後は考え中、返答の直後は読み上げ中とみなす。"""
    assert current_state(entries()[:3]) == "thinking"
    assert current_state(entries()[:4]) == "speaking"


def test_current_state_unknown_when_no_log():
    assert current_state([]) == "unknown"


def test_statistics():
    got = statistics(entries())
    assert got == Statistics(
        ai_calls=3,
        false_wakes=1,
        suppressed=1,  # 「雑音とみなして」1 件（見送り N 回の記録はこのログに無い）
        slow_responses=1,
        errors=0,
        fallback_model="gemini-3.5-flash-lite",
    )


def test_statistics_counts_wakeword_suppressions():
    log = "09/23 14:00:00  状態：聞き取り中…話してください（ウェイクワードを検知、最大 0.80、見送り 3 回）"
    assert statistics([parse_line(log)]).suppressed == 3


def test_read_entries_missing_file(tmp_path):
    assert read_entries(tmp_path / "ない.log") == []


def test_read_entries_reads_tail(tmp_path):
    path = tmp_path / "conversation.log"
    path.write_text(LOG, encoding="utf-8")
    got = read_entries(path, max_lines=3)
    assert len(got) == 3
    assert got[-1].body == "分かりません。"
