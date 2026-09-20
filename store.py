"""
Admin panel va majburiy obuna uchun oddiy SQLite ombor.
Bitta fayl — stats.db bilan bir joyda ishlaydi.
"""
import os
import sqlite3
import time

DB_PATH = "stats.db"

ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
}


def _con():
    return sqlite3.connect(DB_PATH)


def init():
    con = _con()
    con.execute(
        """CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            joined_at INTEGER,
            last_seen INTEGER
        )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )"""
    )
    con.commit()
    con.close()


init()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def touch_user(user_id, name="", username=""):
    now = int(time.time())
    con = _con()
    con.execute(
        """INSERT INTO users(user_id, name, username, joined_at, last_seen)
           VALUES (?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             name=excluded.name, username=excluded.username, last_seen=excluded.last_seen""",
        (user_id, name, username, now, now),
    )
    con.commit()
    con.close()


def all_user_ids():
    con = _con()
    rows = con.execute("SELECT user_id FROM users").fetchall()
    con.close()
    return [r[0] for r in rows]


def user_count():
    con = _con()
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    return n


def get_setting(key, default=None):
    con = _con()
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return row[0] if row else default


def set_setting(key, value):
    con = _con()
    con.execute(
        "INSERT INTO settings(key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    con.commit()
    con.close()


def required_channel():
    return get_setting("required_channel", "")


def game_count():
    con = _con()
    try:
        n = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    con.close()
    return n
