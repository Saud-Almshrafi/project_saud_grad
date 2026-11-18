"""ترحيل: يضيف documents.doc_date_greg (DATE) مع فهرس، ويملؤه للوثائق القديمة.

- آمن للتشغيل أكثر من مرة (idempotent) ولا يحذف ولا يعدّل doc_date.
- يملأ العمود فقط عندما يكون doc_date ميلادياً واضحاً (YYYY-MM-DD أو YYYY/MM/DD أو DD/MM/YYYY
  بسنة بين 1900 واليوم). الهجري والصيغ الغامضة تُترك NULL.

التشغيل (من مجلد المشروع، بنفس إعدادات .env):  python migrate_date_greg.py
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _has_column(cur, engine: str) -> bool:
    if engine == "sqlite":
        cur.execute("PRAGMA table_info(documents)")
        return any(r[1] == "doc_date_greg" for r in cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='documents' AND COLUMN_NAME='doc_date_greg'")
    return _first(cur) > 0


def _has_index(cur, engine: str) -> bool:
    if engine == "sqlite":
        cur.execute("PRAGMA index_list(documents)")
        return any(r[1] == "idx_doc_date_greg" for r in cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='documents' AND INDEX_NAME='idx_doc_date_greg'")
    return _first(cur) > 0


def _first(cur) -> int:
    row = cur.fetchone()
    return int(row[0] if not isinstance(row, dict) else next(iter(row.values())))


def migrate(conn, engine: str) -> dict:
    """ينفّذ الترحيل على اتصال مفتوح ويرجع ملخصاً."""
    from dates import clear_gregorian
    ph = "?" if engine == "sqlite" else "%s"
    cur = conn.cursor()
    added_col = added_idx = False
    if not _has_column(cur, engine):
        cur.execute("ALTER TABLE documents ADD COLUMN doc_date_greg " + ("TEXT" if engine == "sqlite" else "DATE NULL"))
        added_col = True
    if not _has_index(cur, engine):
        cur.execute("CREATE INDEX idx_doc_date_greg ON documents (doc_date_greg)")
        added_idx = True

    cur.execute("SELECT id, doc_date FROM documents WHERE doc_date_greg IS NULL "
                "AND doc_date IS NOT NULL AND TRIM(doc_date) <> ''")
    rows = [(r["id"], r["doc_date"]) if isinstance(r, dict) else (r[0], r[1]) for r in cur.fetchall()]
    migrated = left = 0
    for doc_id, text in rows:
        iso = clear_gregorian(text)
        if iso:
            cur.execute(f"UPDATE documents SET doc_date_greg={ph} WHERE id={ph}", (iso, doc_id))
            migrated += 1
        else:
            left += 1
    cur.execute("SELECT COUNT(*) FROM documents WHERE doc_date IS NULL OR TRIM(doc_date) = ''")
    no_date = _first(cur)
    conn.commit()
    cur.close()
    return {"added_column": added_col, "added_index": added_idx,
            "migrated": migrated, "left_null": left, "no_date_text": no_date}


def main() -> int:
    _load_env()
    import db  # بعد تحميل .env حتى يقرأ DB_ENGINE وبيانات الاتصال
    conn = db._connect()
    try:
        s = migrate(conn, db.ENGINE)
    finally:
        conn.close()
    print("العمود doc_date_greg:", "أُضيف" if s["added_column"] else "موجود مسبقاً")
    print("الفهرس idx_doc_date_greg:", "أُضيف" if s["added_index"] else "موجود مسبقاً")
    print(f"رُحّلت {s['migrated']} وثيقة (تاريخ ميلادي واضح).")
    print(f"تُركت {s['left_null']} وثيقة بدون تاريخ ميلادي (هجري أو صيغة غامضة).")
    print(f"وثائق بلا نص تاريخ أصلاً: {s['no_date_text']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
