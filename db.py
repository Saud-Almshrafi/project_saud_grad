"""طبقة قاعدة البيانات: MySQL للتشغيل الفعلي، SQLite للتجربة السريعة فقط."""
import os
import sqlite3
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
  doc_date TEXT, doc_date_greg TEXT, category_id INTEGER, source TEXT, description TEXT,
  filename TEXT NOT NULL, original_name TEXT NOT NULL, ocr_text TEXT,
  search_text TEXT, summary TEXT, uploaded_by INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_doc_date_greg ON documents (doc_date_greg);
INSERT OR IGNORE INTO categories (name) VALUES
 ('تعميم'),('خطاب'),('قرار'),('محضر'),('نموذج'),('لائحة / تعليمات'),('أخرى');
"""


def _connect():
    if ENGINE == "sqlite":
        path = os.getenv("SQLITE_PATH", "archive_dev.sqlite3")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    import pymysql
    import pymysql.cursors
    return pymysql.connect(
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
    if ENGINE == "sqlite":
        conn.commit()
    last = cur.lastrowid
    cur.close()
    return last


def init_sqlite():
    conn = sqlite3.connect(os.getenv("SQLITE_PATH", "archive_dev.sqlite3"))
    conn.executescript(SQLITE_SCHEMA)
    conn.commit()
    conn.close()
