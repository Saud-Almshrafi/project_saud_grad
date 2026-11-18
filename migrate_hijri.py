"""ترحيل: يضيف documents.doc_date_h (هجري YYYY-MM-DD) مع فهرس، ويملؤه من النص القديم doc_date.

- آمن للتشغيل أكثر من مرة (idempotent).
- لا يحذف ولا يعدّل doc_date، ولا يكتب فوق وثيقة سبق تعبئة تاريخها.
- يستخدم parse_any_date: الهجري يُنقل كما هو، والميلادي الواضح يُحوَّل إلى هجري،
  والغامض أو غير الصالح أو المستقبلي يُترك NULL (بلا تخمين).

⚠ خذ نسخة احتياطية من قاعدة البيانات قبل التشغيل (انظر README.md).
التشغيل من مجلد المشروع، بنفس إعدادات .env:  python migrate_hijri.py
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


def _val(row, i, key):
    return row[key] if isinstance(row, dict) else row[i]


def _count(cur) -> int:
    row = cur.fetchone()
    return int(next(iter(row.values())) if isinstance(row, dict) else row[0])


def _has_column(cur, engine):
    if engine == "sqlite":
        cur.execute("PRAGMA table_info(documents)")
        return any(_val(r, 1, "name") == "doc_date_h" for r in cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='documents' AND COLUMN_NAME='doc_date_h'")
    return _count(cur) > 0


def _has_index(cur, engine):
    if engine == "sqlite":
        cur.execute("PRAGMA index_list(documents)")
        return any(_val(r, 1, "name") == "idx_doc_date_h" for r in cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='documents' AND INDEX_NAME='idx_doc_date_h'")
    return _count(cur) > 0


def migrate(conn, engine: str) -> dict:
    """ينفّذ الترحيل على اتصال مفتوح ويرجع ملخصاً."""
    from hijri_utils import parse_any_date_kind, today_hijri
    ph = "?" if engine == "sqlite" else "%s"
    today = today_hijri()
    cur = conn.cursor()
    added_col = added_idx = False
    if not _has_column(cur, engine):
        cur.execute("ALTER TABLE documents ADD COLUMN doc_date_h " + ("TEXT" if engine == "sqlite" else "CHAR(10) NULL"))
        added_col = True
    if not _has_index(cur, engine):
        cur.execute("CREATE INDEX idx_doc_date_h ON documents (doc_date_h)")
        added_idx = True

    # فقط الوثائق التي لم تُعبّأ بعد: لا نكتب فوق تاريخ موجود
    cur.execute("SELECT id, doc_date FROM documents WHERE doc_date_h IS NULL ORDER BY id")
    rows = [(_val(r, 0, "id"), _val(r, 1, "doc_date")) for r in cur.fetchall()]
    from_hijri, from_greg, unparsed, empty = [], [], [], []
    for doc_id, text in rows:
        if not (text or "").strip():
            empty.append(doc_id)
            continue
        res = parse_any_date_kind(text)
        if not res or res[0] > today:  # غامض/غير صالح/مستقبلي → بلا تخمين
            unparsed.append(doc_id)
            continue
        cur.execute(f"UPDATE documents SET doc_date_h={ph} WHERE id={ph} AND doc_date_h IS NULL", (res[0], doc_id))
        (from_hijri if res[1] == "h" else from_greg).append(doc_id)
    conn.commit()
    cur.close()
    return {"added_column": added_col, "added_index": added_idx, "from_hijri": from_hijri,
            "from_greg": from_greg, "unparsed": unparsed, "empty": empty}


def main() -> int:
    _load_env()
    import db  # بعد تحميل .env حتى يقرأ DB_ENGINE وبيانات الاتصال
    conn = db._connect()
    try:
        s = migrate(conn, db.ENGINE)
    finally:
        conn.close()
    ids = lambda lst: ", ".join(map(str, lst)) if lst else "—"
    print("العمود doc_date_h:", "أُضيف" if s["added_column"] else "موجود مسبقاً")
    print("الفهرس idx_doc_date_h:", "أُضيف" if s["added_index"] else "موجود مسبقاً")
    print(f"رُحّلت من تاريخ هجري: {len(s['from_hijri'])} وثيقة")
    print(f"حُوّلت من تاريخ ميلادي إلى هجري: {len(s['from_greg'])} وثيقة")
    left = s["unparsed"] + s["empty"]
    print(f"تُركت بلا تاريخ: {len(left)} وثيقة")
    print(f"  - نص تاريخ غامض أو غير صالح أو مستقبلي ({len(s['unparsed'])}): المعرّفات {ids(s['unparsed'])}")
    print(f"  - بلا نص تاريخ أصلاً ({len(s['empty'])}): المعرّفات {ids(s['empty'])}")
    print("الوثائق التي سبق تعبئة تاريخها لم تُلمس.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
