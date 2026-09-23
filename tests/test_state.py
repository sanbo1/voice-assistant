import json
import os
from datetime import datetime

from voice_assistant.state import WAITING, StateFile, default_path


def fixed_clock(text="2026-09-23T14:30:00"):
    return lambda: datetime.fromisoformat(text)


def test_writes_state_and_pid(tmp_path):
    path = tmp_path / "state.json"
    StateFile(path, clock=fixed_clock()).write(WAITING)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["state"] == WAITING
    assert data["updated"] == "2026-09-23T14:30:00"
    assert data["pid"] == os.getpid()


def test_history_deadline_is_written_when_alive(tmp_path):
    """会話履歴が生きている間だけ、消える時刻を書く（画面が過去の出し方を変えるため）。"""
    path = tmp_path / "state.json"
    StateFile(path, clock=fixed_clock()).write(WAITING, history_seconds_left=300.0)
    assert json.loads(path.read_text(encoding="utf-8"))["history_alive_until"] == "2026-09-23T14:35:00"


def test_history_deadline_is_omitted_when_empty(tmp_path):
    path = tmp_path / "state.json"
    StateFile(path, clock=fixed_clock()).write(WAITING, history_seconds_left=0.0)
    assert "history_alive_until" not in json.loads(path.read_text(encoding="utf-8"))


def test_creates_parent_directory(tmp_path):
    path = tmp_path / "voice-assistant" / "state.json"
    StateFile(path).write(WAITING)
    assert path.exists()


def test_leaves_no_temporary_file(tmp_path):
    """読みかけを見せないよう別名で書いてから置き換える。後始末も確かめる。"""
    path = tmp_path / "state.json"
    StateFile(path).write(WAITING)
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_write_failure_does_not_raise(tmp_path):
    """状態ファイルは画面のためのもの。書けなくても本体を止めない。"""
    path = tmp_path / "file-in-the-way" / "state.json"
    (tmp_path / "file-in-the-way").write_text("これはフォルダではない", encoding="utf-8")
    StateFile(path).write(WAITING)  # 例外が出ないこと


def test_no_path_is_harmless():
    StateFile(None).write(WAITING)  # 例外が出ないこと
    assert StateFile(None).path is None


def test_remove(tmp_path):
    path = tmp_path / "state.json"
    state = StateFile(path)
    state.write(WAITING)
    state.remove()
    assert not path.exists()
    state.remove()  # 2 回目も例外が出ないこと


def test_default_path_uses_runtime_dir(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert default_path().as_posix().endswith("/run/user/1000/voice-assistant/state.json")


def test_default_path_without_runtime_dir(monkeypatch):
    """置き場所が決まらなければ書かない（SD カードには書かない）。"""
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert default_path() is None
