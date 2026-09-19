import pytest

from voice_assistant.ai import AiError
from voice_assistant.ai.fallback import RETRY_SECONDS, FallbackChatClient

DAILY = AiError("1 日の上限", status=429, quota="day")
MINUTE = AiError("1 分の上限", status=429, quota="minute")
BUSY = AiError("混雑", status=503)
TIMEOUT = AiError("時間切れ")
BAD_KEY = AiError("API キーが無効", status=400)


class FakeModel:
    """reply のたびに results の先頭を返す（例外なら投げる）。results が空なら「<名前>の返答」。"""

    def __init__(self, name, results=()):
        self.name = name
        self.results = list(results)
        self.calls = 0

    def reply(self, user_text, history=()):
        self.calls += 1
        result = self.results.pop(0) if self.results else f"{self.name}の返答"
        if isinstance(result, Exception):
            raise result
        return result


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make(*models):
    statuses = []
    clock = Clock()
    client = FallbackChatClient([(m.name, m) for m in models], on_status=statuses.append, clock=clock)
    return client, statuses, clock


def test_primary_answers():
    a, b = FakeModel("A"), FakeModel("B")
    client, statuses, _ = make(a, b)
    assert client.reply("質問") == "Aの返答"
    assert (client.last_model, b.calls, statuses) == ("A", 0, [])


def test_daily_limit_switches_and_skips_primary_for_an_hour():
    a, b = FakeModel("A", [DAILY]), FakeModel("B")
    client, statuses, clock = make(a, b)
    assert client.reply("質問1") == "Bの返答"
    assert statuses == ["A が今日の上限に達しました。1 時間ごとに確認します", "B に切り替えました"]
    assert client.last_model == "B"

    clock.now = RETRY_SECONDS - 1
    assert client.reply("質問2") == "Bの返答"
    assert a.calls == 1  # 1 時間たつまでは A を試さない


def test_returns_to_primary_after_recovery():
    a, b = FakeModel("A", [DAILY]), FakeModel("B")
    client, statuses, clock = make(a, b)
    client.reply("質問1")
    clock.now = RETRY_SECONDS + 1
    assert client.reply("質問2") == "Aの返答"
    assert statuses[-1] == "A に戻りました"
    assert client.last_model == "A"


def test_still_over_limit_after_an_hour_is_not_announced_again():
    a, b = FakeModel("A", [DAILY, DAILY]), FakeModel("B")
    client, statuses, clock = make(a, b)
    client.reply("質問1")
    clock.now = RETRY_SECONDS + 1
    assert client.reply("質問2") == "Bの返答"
    assert a.calls == 2
    assert len(statuses) == 2  # 「上限に達しました」と「切り替えました」は 1 回だけ


@pytest.mark.parametrize("error", [MINUTE, BUSY, TIMEOUT])
def test_temporary_error_uses_next_model_only_for_that_question(error):
    a, b = FakeModel("A", [error]), FakeModel("B")
    client, statuses, _ = make(a, b)
    assert client.reply("質問1") == "Bの返答"
    assert client.reply("質問2") == "Aの返答"  # 次の質問では A を試す
    assert statuses == ["B に切り替えました", "A に戻りました"]


def test_configuration_error_is_raised_immediately():
    a, b = FakeModel("A", [BAD_KEY]), FakeModel("B")
    client, _, _ = make(a, b)
    with pytest.raises(AiError, match="API キー"):
        client.reply("質問")
    assert b.calls == 0


def test_all_models_over_daily_limit():
    a, b = FakeModel("A", [DAILY]), FakeModel("B", [DAILY])
    client, _, _ = make(a, b)
    with pytest.raises(AiError) as e:
        client.reply("質問1")
    assert (e.value.status, e.value.quota) == (429, "day")
    # どちらも 1 時間は試さずに、同じエラーにする
    with pytest.raises(AiError) as e:
        client.reply("質問2")
    assert e.value.quota == "day"
    assert (a.calls, b.calls) == (1, 1)


def test_last_temporary_error_is_raised_when_all_fail():
    a, b = FakeModel("A", [DAILY]), FakeModel("B", [BUSY])
    client, _, _ = make(a, b)
    with pytest.raises(AiError, match="混雑"):
        client.reply("質問")
