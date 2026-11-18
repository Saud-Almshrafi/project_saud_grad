"""ترحيل: سجل التعديلات.

- يضيف إلى documents: updated_at DATETIME NULL و updated_by INT NULL (مرجع users.id، ON DELETE SET NULL).
- ينشئ جدول document_edits (document_id → CASCADE، user_id → SET NULL).
- آمن للتشغيل أكثر من مرة (idempotent)، ولا يحذف ولا يعدّل أي بيانات.
- الوثائق الموجودة تبقى updated_at = NULL (أي: لم تُعدَّل منذ رفعها). لا نخترع تاريخاً لها.

⚠ خذ نسخة احتياطية من قاعدة البيانات قبل التشغيل (انظر README.md).
التشغيل من مجلد المشروع، بنفس إعدادات .env:  python migrate_edit_log.py
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MYSQL_EDITS_TABLE = """
CREATE TABLE IF NOT EXISTS document_edits (
  id INT AUTO_INCREMENT PRIMARY KEY,
  document_id INT NOT NULL,
  user_id INT NULL,
  edited_at DATETIME NOT NULL,
  changes TEXT NOT NULL,
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_edits_doc (document_id, edited_at)
) ENGINE=InnoDB"""

SQLITE_EDITS_TABLE = """
CREATE TABLE IF NOT EXISTS document_edits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  edited_at TEXT NOT NULL, changes TEXT NOT NULL)"""


def _load_env():
    path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _scalar(cur) -> int:
    row = cur.fetchone()
    return int(next(iter(row.values())) if isinstance(row, dict) else row[0])


def _columns(cur, engine, table):
    if engine == "sqlite":
        cur.execute(f"PRAGMA table_info({table})")
        return {(r["name"] if isinstance(r, dict) else r[1]) for r in cur.fetchall()}
    cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
                (table,))
    return {(r["COLUMN_NAME"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}


def _table_exists(cur, engine, table):
    if engine == "sqlite":
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
    else:
        cur.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
                    (table,))
    return _scalar(cur) > 0


def _mysql_fk_exists(cur):
    cur.execute("SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='documents' AND COLUMN_NAME='updated_by' AND REFERENCED_TABLE_NAME='users'")
    return _scalar(cur) > 0


def migrate(conn, engine: str) -> dict:
    cur = conn.cursor()
    done = []
    cols = _columns(cur, engine, "documents")
    if "updated_at" not in cols:
        cur.execute("ALTER TABLE documents ADD COLUMN updated_at " + ("TEXT" if engine == "sqlite" else "DATETIME NULL"))
        done.append("documents.updated_at")
    if "updated_by" not in cols:
        if engine == "sqlite":
            cur.execute("ALTER TABLE documents ADD COLUMN updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL")
        else:
            cur.execute("ALTER TABLE documents ADD COLUMN updated_by INT NULL")
        done.append("documents.updated_by")
    if engine != "sqlite" and not _mysql_fk_exists(cur):
        cur.execute("ALTER TABLE documents ADD CONSTRAINT fk_documents_updated_by "
                    "FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL")
        done.append("fk_documents_updated_by")
    if not _table_exists(cur, engine, "document_edits"):
        cur.execute(SQLITE_EDITS_TABLE if engine == "sqlite" else MYSQL_EDITS_TABLE)
        if engine == "sqlite":
            cur.execute("CREATE INDEX IF NOT EXISTS idx_edits_doc ON document_edits (document_id, edited_at)")
        done.append("document_edits")
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM documents")
    total = _scalar(cur)
    cur.execute("SELECT COUNT(*) FROM documents WHERE updated_at IS NOT NULL")
    edited = _scalar(cur)
    cur.close()
    return {"done": done, "documents": total, "edited": edited}


def main() -> int:
    _load_env()
    import db  # بعد تحميل .env
    conn = db._connect()
    try:
        s = migrate(conn, db.ENGINE)
    finally:
        conn.close()
    if s["done"]:
        print("أُضيف:", "، ".join(s["done"]))
    else:
        print("لا شيء جديد: كل الأعمدة والجداول موجودة مسبقاً.")
    print(f"الوثائق: {s['documents']} (منها {s['edited']} لها تاريخ تعديل؛ الباقي «لم تُعدَّل منذ رفعها»).")
    print("لم تُحذف ولم تُعدَّل أي بيانات.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
