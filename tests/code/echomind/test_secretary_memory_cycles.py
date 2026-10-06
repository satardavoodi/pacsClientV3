import sqlite3
from modules.EchoMind.secretary.memory import memory_store as ms


def test_cycles_rollover_new_and_independent_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "_MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(ms, "_db_conn", lambda: sqlite3.connect(tmp_path / "test.db"))
    store = ms.EchoMindMemoryStore()
    number = store.get_current_info()[0]
    for count in range(1, 11):
        store.start_cycle("Synthetic command")
        store.close_cycle()
        store.close_cycle()
        assert store.get_current_info() == (number, count)
    previous = store._filepath
    store.start_cycle("Eleventh command")
    store.close_cycle()
    assert store.get_current_info() == (number + 1, 1)
    assert previous.exists()
    other = ms.EchoMindMemoryStore()
    store.new_memory()
    assert store.get_current_info() == (other.get_current_info()[0] + 1, 0)
    assert store.get_context_for_llm() == ""
    store.start_cycle("New request")
    store.close_cycle()
    assert store.get_current_info()[1] == 1
