import os

from voice_assistant.settings import (
    SettingsWatcher,
    changes,
    load_settings,
    needs_restart,
    read_env,
)


def base():
    return load_settings({})


def test_changes_lists_what_moved():
    before = base()
    after = load_settings({"WAKEWORD_CONFIRM_THRESHOLD": "0.6", "FOLLOWUP_SECONDS": "5"})
    got = changes(before, after)
    assert "続けて話せる秒数 3.0 → 5.0" in got
    assert "ウェイクワードの確認しきい値 0.52 → 0.6" in got or \
           "ウェイクワードの確認しきい値 0.0 → 0.6" in got


def test_changes_names_the_key_and_wake_turns_separately():
    got = changes(base(), load_settings({"FOLLOWUP_MAX_TURNS": "2", "FOLLOWUP_MAX_TURNS_KEY": "1"}))
    assert "続けて話せる回数（ウェイクワード） 3 → 2" in got
    assert "続けて話せる回数（スペースキー） 0 → 1" in got


def test_changes_is_empty_when_nothing_moved():
    assert changes(base(), base()) == []


def test_api_key_value_is_never_shown():
    """API キーは値を出さない（会話ログは画面に表示されるため）。"""
    after = load_settings({"GEMINI_API_KEY": "秘密の値"})
    got = changes(base(), after)
    assert got == ["API キーを変更しました"]
    assert "秘密の値" not in "".join(got)


def test_needs_restart_only_for_the_model():
    before = base()
    assert needs_restart(before, load_settings({"VOSK_MODEL_DIR": "vosk-model-small-ja-0.22"})) == \
        ["音声認識のモデル"]
    assert needs_restart(before, load_settings({"WAKEWORD_THRESHOLD": "0.5"})) == []


def test_read_env_prefers_the_file(tmp_path, monkeypatch):
    """読み直しでは .env を優先する（利用者が編集するのは .env のため）。"""
    monkeypatch.setenv("WAKEWORD_THRESHOLD", "0.9")
    path = tmp_path / ".env"
    path.write_text("WAKEWORD_THRESHOLD=0.3\n", encoding="utf-8")
    assert read_env(path)["WAKEWORD_THRESHOLD"] == "0.3"


def test_read_env_keeps_other_environment_values(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLLOWUP_SECONDS", "7")
    path = tmp_path / ".env"
    path.write_text("WAKEWORD_THRESHOLD=0.3\n", encoding="utf-8")
    assert read_env(path)["FOLLOWUP_SECONDS"] == "7"


# ---------- 変更の見張り ----------


def write_env(path, text):
    path.write_text(text, encoding="utf-8")
    # 更新時刻が変わったことを確実にする（同じ秒に書くと気づけない環境があるため）
    stat = path.stat()
    os.utime(path, (stat.st_atime + 10, stat.st_mtime + 10))


def test_watcher_returns_none_without_changes(tmp_path):
    path = tmp_path / ".env"
    path.write_text("WAKEWORD_THRESHOLD=0.35\n", encoding="utf-8")
    watcher = SettingsWatcher(load_settings({}), path)
    assert watcher.reload_if_changed() is None


def test_watcher_detects_a_change(tmp_path, monkeypatch):
    monkeypatch.delenv("FOLLOWUP_SECONDS", raising=False)
    path = tmp_path / ".env"
    path.write_text("FOLLOWUP_SECONDS=3\n", encoding="utf-8")
    watcher = SettingsWatcher(load_settings({}), path)
    write_env(path, "FOLLOWUP_SECONDS=8\n")
    new = watcher.reload_if_changed()
    assert new is not None and new.assistant.followup_seconds == 8.0
    assert watcher.settings is new
    assert watcher.reload_if_changed() is None  # 2 回目は変化なし


def test_watcher_ignores_edits_that_change_nothing(tmp_path):
    """コメントを足しただけなど、設定が変わらない編集では何もしない。"""
    path = tmp_path / ".env"
    path.write_text("FOLLOWUP_SECONDS=3\n", encoding="utf-8")
    watcher = SettingsWatcher(load_settings({"FOLLOWUP_SECONDS": "3"}), path)
    write_env(path, "# メモ\nFOLLOWUP_SECONDS=3\n")
    assert watcher.reload_if_changed() is None


def test_watcher_survives_a_missing_file(tmp_path):
    """.env が無くても本体を止めない。"""
    path = tmp_path / ".env"
    watcher = SettingsWatcher(load_settings({}), path)
    assert watcher.reload_if_changed() is None
