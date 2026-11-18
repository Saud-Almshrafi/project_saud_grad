"""ترحيل: فهرس على documents.created_at لتسريع البحث بتاريخ الرفع.

- آمن للتشغيل أكثر من مرة (idempotent): لا يضيف الفهرس إن وُجد أي فهرس يبدأ بالعمود created_at.
- لا يحذف ولا يعدّل أي بيانات.

⚠ خذ نسخة احتياطية من قاعدة البيانات قبل التشغيل (انظر README.md).
التشغيل من مجلد المشروع، بنفس إعدادات .env:  python migrate_created_index.py
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


def _scalar(cur) -> int:
    row = cur.fetchone()
    return int(next(iter(row.values())) if isinstance(row, dict) else row[0])


def has_created_index(cur, engine: str) -> bool:
    if engine == "sqlite":
        cur.execute("SELECT COUNT(*) FROM pragma_index_list('documents') AS il "
                    "JOIN pragma_index_info(il.name) AS ii WHERE ii.seqno = 0 AND ii.name = 'created_at'")
        return _scalar(cur) > 0
    cur.execute("SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='documents' AND COLUMN_NAME='created_at' AND SEQ_IN_INDEX=1")
    return _scalar(cur) > 0


def migrate(conn, engine: str) -> dict:
    cur = conn.cursor()
    added = False
    if not has_created_index(cur, engine):
        cur.execute("CREATE INDEX idx_created_at ON documents (created_at)")
        added = True
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM documents WHERE created_at IS NULL")
    null_created = _scalar(cur)
    cur.close()
    return {"added_index": added, "null_created_at": null_created}


def main() -> int:
    _load_env()
    import db  # بعد تحميل .env
    conn = db._connect()
    try:
        s = migrate(conn, db.ENGINE)
    finally:
        conn.close()
    print("الفهرس idx_created_at:", "أُضيف" if s["added_index"] else "موجود مسبقاً")
    print(f"وثائق بلا تاريخ رفع (created_at فارغ): {s['null_created_at']}")
    print("لم تُحذف ولم تُعدَّل أي بيانات.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
