"""طبقة قاعدة البيانات: MySQL للتشغيل الفعلي، SQLite للتجربة السريعة فقط."""
import os
import sqlite3
from contextlib import contextmanager

from flask import g

ENGINE = os.getenv("DB_ENGINE", "mysql").lower()

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
  full_name TEXT NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, doc_number TEXT,
  doc_date TEXT, doc_date_h TEXT, category_id INTEGER, source TEXT, description TEXT,
  filename TEXT NOT NULL, original_name TEXT NOT NULL, ocr_text TEXT,
  search_text TEXT, summary TEXT, uploaded_by INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT, updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS idx_doc_date_h ON documents (doc_date_h);
CREATE TABLE IF NOT EXISTS document_edits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  edited_at TEXT NOT NULL, changes TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_edits_doc ON document_edits (document_id, edited_at);
INSERT OR IGNORE INTO categories (name) VALUES
 ('تعميم'),('خطاب'),('قرار'),('محضر'),('نموذج'),('لائحة / تعليمات'),('أخرى');
"""


def _connect():
    if ENGINE == "sqlite":
        path = os.getenv("SQLITE_PATH", "archive_dev.sqlite3")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")  # لتعمل ON DELETE CASCADE / SET NULL
        return conn
    import pymysql
    import pymysql.cursors
    # الجلسة بتوقيت UTC: created_at (TIMESTAMP) يُقرأ UTC مهما كان توقيت جهاز الخادم،
    # ونخزّن updated_at/edited_at (DATETIME) UTC أيضاً، ونحوّل للرياض عند العرض فقط.
    return pymysql.connect(
        init_command="SET time_zone = '+00:00'",
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "archive_db"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _sql(sql):
    return sql.replace("%s", "?") if ENGINE == "sqlite" else sql


def query(sql, params=(), one=False):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_sql(sql), params)
    rows = cur.fetchall()
    rows = [dict(r) for r in rows]
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_sql(sql), params)
    if ENGINE == "sqlite" and not g.get("in_tx"):
        conn.commit()
    last = cur.lastrowid
    cur.close()
    return last


@contextmanager
def transaction():
    """ينفّذ عدة execute كوحدة واحدة: إما تُحفظ كلها أو لا يُحفظ شيء."""
    conn = get_db()
    if ENGINE != "sqlite":
        conn.begin()  # START TRANSACTION (يعلّق autocommit حتى commit/rollback)
    g.in_tx = True
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        g.in_tx = False


def init_sqlite():
    conn = sqlite3.connect(os.getenv("SQLITE_PATH", "archive_dev.sqlite3"))
    conn.executescript(SQLITE_SCHEMA)
    conn.commit()
    conn.close()
