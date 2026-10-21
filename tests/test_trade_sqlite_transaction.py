"""Real SQLite commit boundaries; no broker or research assets."""
import sqlite3

import pytest

from Trade.SqliteDB import CSqliteDB


@pytest.fixture()
def store(tmp_path):
    path = str(tmp_path/"transaction.db")
    db = CSqliteDB(path)
    db.execute("CREATE TABLE notes(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    reader = sqlite3.connect(path)
    try:
        yield db, reader
    finally:
        reader.close()
        db.close()


def test_execute_keeps_its_existing_standalone_commit(store):
    db, reader = store
    assert db.execute("INSERT INTO notes(value) VALUES(?)", ("standalone",)) == 1
    assert reader.execute("SELECT value FROM notes").fetchall() == [("standalone",)]


def test_a_transaction_does_not_publish_intermediate_statements(store):
    db, reader = store
    with db.transaction():
        db.execute("INSERT INTO notes(value) VALUES(?)", ("first",))
        assert reader.execute("SELECT value FROM notes").fetchall() == []
        db.execute("INSERT INTO notes(value) VALUES(?)", ("second",))
        assert reader.execute("SELECT value FROM notes").fetchall() == []
    assert reader.execute("SELECT value FROM notes ORDER BY id").fetchall() == [("first",), ("second",)]


def test_failure_rolls_back_every_statement_and_releases_the_writer(store):
    db, reader = store
    with pytest.raises(ValueError, match="audit failed"):
        with db.transaction():
            db.execute("INSERT INTO notes(value) VALUES(?)", ("must disappear",))
            raise ValueError("audit failed")
    assert reader.execute("SELECT value FROM notes").fetchall() == []
    assert not db.conn.in_transaction
    db.execute("INSERT INTO notes(value) VALUES(?)", ("next",))
    assert reader.execute("SELECT value FROM notes").fetchall() == [("next",)]


def test_nested_savepoint_can_roll_back_without_losing_the_outer_transaction(store):
    db, reader = store
    with db.transaction():
        db.execute("INSERT INTO notes(value) VALUES(?)", ("outer",))
        with pytest.raises(ValueError):
            with db.transaction():
                db.execute("INSERT INTO notes(value) VALUES(?)", ("inner rollback",))
                raise ValueError("rollback inner")
        with db.transaction():
            db.execute("INSERT INTO notes(value) VALUES(?)", ("inner kept",))
        assert reader.execute("SELECT value FROM notes").fetchall() == []
    assert reader.execute("SELECT value FROM notes ORDER BY id").fetchall() == [("outer",), ("inner kept",)]


def test_outer_failure_also_rolls_back_a_released_inner_savepoint(store):
    db, reader = store
    with pytest.raises(RuntimeError):
        with db.transaction():
            with db.transaction():
                db.execute("INSERT INTO notes(value) VALUES(?)", ("released, not committed",))
            raise RuntimeError("outer failed")
    assert reader.execute("SELECT value FROM notes").fetchall() == []


def test_a_failed_standalone_statement_does_not_leave_an_open_transaction(store):
    db, reader = store
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO notes(value) VALUES(NULL)")
    assert not db.conn.in_transaction
    db.execute("INSERT INTO notes(value) VALUES(?)", ("usable",))
    assert reader.execute("SELECT value FROM notes").fetchall() == [("usable",)]
