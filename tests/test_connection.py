import threading

from yolk.db.connection import connect


def test_a_connection_can_be_opened_for_use_on_another_thread(tmp_path):
    """The web app opens a connection in a dependency and may use it in a
    route running on a different threadpool thread."""
    conn = connect(tmp_path / "t.db", check_same_thread=False)
    seen: list[int] = []
    worker = threading.Thread(
        target=lambda: seen.append(conn.execute("SELECT 1 AS n").fetchone()["n"])
    )
    worker.start()
    worker.join()
    conn.close()
    assert seen == [1]
