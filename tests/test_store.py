from kayaai.core.store import TaskStore
from kayaai.core.task import Task, TaskStatus


def test_save_get_list_and_events(store):
    t = Task(worker="general", objective="deneme")
    store.save(t)
    store.log_event(t.id, "submitted", {"x": "ğüşiöç"})
    got = store.get(t.id)
    assert got == t
    assert [x.id for x in store.list_tasks()] == [t.id]
    assert store.events(t.id)[0]["event"] == "submitted"
    assert "ğüşiöç" in store.events(t.id)[0]["detail"]


def test_history_survives_restart_and_interrupted_marked_failed(tmp_path):
    """Kabul testi #13: sistem yeniden başlayınca görev geçmişi geri yüklenir."""
    db = tmp_path / "kayaai.db"
    s1 = TaskStore(db)
    done = Task(worker="general", objective="tamamlanan", status=TaskStatus.SUCCEEDED, result={"answer": "ok"})
    half = Task(worker="general", objective="yarım kalan", status=TaskStatus.RUNNING)
    s1.save(done)
    s1.save(half)
    s1.close()  # "çökme"

    s2 = TaskStore(db)
    recovered = s2.recover_interrupted()
    assert recovered == [half.id]
    assert s2.get(done.id).status == TaskStatus.SUCCEEDED
    assert s2.get(done.id).result == {"answer": "ok"}
    h = s2.get(half.id)
    assert h.status == TaskStatus.FAILED and "interrupted" in h.error
    assert s2.count() == 2
    s2.close()
