"""ترحيل: عمود documents.doc_date_source (مصدر تاريخ الوثيقة: auto / manual / backfill).

- آمن للتشغيل أكثر من مرة (idempotent)، ولا يحذف ولا يعدّل أي بيانات.
- الوثائق الموجودة يبقى مصدرها NULL (غير معروف): لا نخترع مصدراً لتاريخ سبق تعبئته.

⚠ خذ نسخة احتياطية من قاعدة البيانات قبل التشغيل (انظر README.md).
التشغيل من مجلد المشروع، بنفس إعدادات .env:  python migrate_doc_date_source.py
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


def has_column(cur, engine: str) -> bool:
    if engine == "sqlite":
        cur.execute("SELECT COUNT(*) FROM pragma_table_info('documents') WHERE name='doc_date_source'")
    else:
        cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                    "AND TABLE_NAME='documents' AND COLUMN_NAME='doc_date_source'")
    row = cur.fetchone()
    return int(next(iter(row.values())) if isinstance(row, dict) else row[0]) > 0


def migrate(conn, engine: str) -> dict:
    cur = conn.cursor()
    added = False
    if not has_column(cur, engine):
        cur.execute("ALTER TABLE documents ADD COLUMN doc_date_source " + ("TEXT" if engine == "sqlite" else "VARCHAR(10) NULL"))
        added = True
    conn.commit()
    cur.close()
    return {"added_column": added}


def main() -> int:
    _load_env()
    import db  # بعد تحميل .env
    conn = db._connect()
    try:
        s = migrate(conn, db.ENGINE)
    finally:
        conn.close()
    print("العمود doc_date_source:", "أُضيف" if s["added_column"] else "موجود مسبقاً")
    print("لم تُحذف ولم تُعدَّل أي بيانات.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
