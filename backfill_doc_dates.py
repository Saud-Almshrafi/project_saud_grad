"""تعبئة تاريخ الوثيقة للوثائق القديمة التي بلا تاريخ (doc_date_h فارغ).

الاستخدام (من مجلد المشروع، بنفس إعدادات .env):
    python backfill_doc_dates.py               # تجربة فقط (dry-run): يعرض ما سيفعله دون أي كتابة
    python backfill_doc_dates.py --apply       # تنفيذ فعلي — ⚠ خذ نسخة احتياطية قبلها (README.md)
    python backfill_doc_dates.py --apply --use-ai   # يستعين بـ Gemini أيضاً (يرسل نص الوثيقة إلى Google)

القواعد:
- يعمل فقط على الوثائق التي doc_date_h فيها NULL، ولا يكتب فوق أي تاريخ موجود أبداً.
- يستخرج من النص المخزّن (ocr_text) بالتعابير النمطية؛ ولا يستدعي Gemini إلا مع --use-ai.
- لا يعبّئ إلا عند ثقة عالية (تاريخ واحد واضح مقترن بكلمة «التاريخ» أو ما يشبهها). ما سواه يُترك
  لصفحة «وثائق تحتاج تاريخاً».
- يضع doc_date_source = backfill ويضيف صفاً في document_edits بلا مستخدم ("تعبئة تلقائية لتاريخ الوثيقة")،
  ولا يغيّر updated_at ولا updated_by (ليس تعديلاً من مستخدم).
- لا يستعمل تاريخ الأرشفة (created_at) بديلاً أبداً.
- Idempotent: تشغيله مرتين لا يكرر شيئاً (الوثائق المعبّأة لم تعد NULL).
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NOTE = "تعبئة تلقائية لتاريخ الوثيقة"
REASONS = {"no_text": "لا يوجد نص مخزّن للوثيقة", "no_date": "لا يوجد تاريخ في النص",
           "ambiguous": "عدة تواريخ بلا ترجيح واضح", "reference_only": "التاريخ الوحيد إشارة لوثيقة أخرى في المتن",
           "no_keyword": "تاريخ غير مقترن بكلمة «التاريخ»", "single_in_header": "تاريخ بلا كلمة «التاريخ» (ثقة متوسطة)",
           "future": "التاريخ بعد اليوم الهجري"}


def _load_env():
    path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _rows(cur):
    out = []
    for r in cur.fetchall():
        out.append(r if isinstance(r, dict) else {"id": r[0], "title": r[1], "ocr_text": r[2]})
    return out


def backfill(conn, engine: str, apply: bool = False, use_ai: bool = False, today: str | None = None) -> dict:
    """ينفّذ التعبئة (أو يجرّبها) ويرجع تقريراً: {filled: [(id, iso, method)], left: [(id, reason)]}."""
    import ai
    import hijri_utils as hu
    today = today or hu.today_hijri()
    ph = "?" if engine == "sqlite" else "%s"
    cur = conn.cursor()
    cur.execute("SELECT id, title, ocr_text FROM documents WHERE doc_date_h IS NULL ORDER BY id")
    docs = _rows(cur)
    cats = []
    if use_ai:
        cur.execute("SELECT name FROM categories")
        cats = [r["name"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
    filled, left = [], []
    for d in docs:
        text = (d["ocr_text"] or "").strip()
        if not text:
            left.append((d["id"], "no_text"))
            continue
        gem = ai.gemini_analyze(text, cats) if use_ai else None
        res = ai.extract_document_date(text, gem, today=today)
        if not res["iso"] or res["confidence"] != "high":  # ثقة عالية فقط
            left.append((d["id"], res["reason"] if not res["iso"] else "single_in_header"))
            continue
        filled.append((d["id"], res["iso"], res["method"]))
        if not apply:
            continue
        changes = [{"field": "doc_date_h", "label": "التاريخ", "old": None, "new": hu.format_hijri(res["iso"]),
                    "note": NOTE, "source": "backfill"}]
        if engine != "sqlite":
            conn.begin()
        try:  # التعبئة والسجل معاً أو لا شيء. لا نلمس updated_at/updated_by.
            cur.execute(f"UPDATE documents SET doc_date_h={ph}, doc_date_source='backfill' "
                        f"WHERE id={ph} AND doc_date_h IS NULL", (res["iso"], d["id"]))
            if cur.rowcount == 1:
                cur.execute(f"INSERT INTO document_edits (document_id, user_id, edited_at, changes) VALUES ({ph},NULL,{ph},{ph})",
                            (d["id"], hu.utc_now_str(), json.dumps(changes, ensure_ascii=False)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    cur.close()
    return {"filled": filled, "left": left, "checked": len(docs), "applied": apply}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="تعبئة تاريخ الوثيقة للوثائق القديمة التي بلا تاريخ.")
    ap.add_argument("--apply", action="store_true", help="تنفيذ فعلي (الافتراضي: تجربة فقط دون كتابة)")
    ap.add_argument("--use-ai", action="store_true", help="الاستعانة بـ Gemini أيضاً (يرسل نص الوثيقة إلى Google)")
    args = ap.parse_args(argv)
    _load_env()
    import db  # بعد تحميل .env
    import hijri_utils as hu
    conn = db._connect()
    try:
        r = backfill(conn, db.ENGINE, apply=args.apply, use_ai=args.use_ai)
    finally:
        conn.close()
    mode = "تنفيذ فعلي" if r["applied"] else "تجربة فقط (dry-run) — لم يُكتب شيء؛ للتنفيذ أضف --apply"
    print(f"الوضع: {mode}")
    print(f"وثائق بلا تاريخ فُحصت: {r['checked']}")
    print(f"{'عُبّئت' if r['applied'] else 'ستُعبّأ'}: {len(r['filled'])}")
    for doc_id, iso, method in r["filled"]:
        print(f"  - #{doc_id}: {hu.format_hijri(iso)} ({'Gemini' if method == 'gemini' else 'من النص'})")
    print(f"تُركت للصفحة اليدوية: {len(r['left'])}")
    by_reason = {}
    for doc_id, reason in r["left"]:
        by_reason.setdefault(reason, []).append(doc_id)
    for reason, ids in by_reason.items():
        print(f"  - {REASONS.get(reason, reason)}: {len(ids)} — المعرّفات: {', '.join(map(str, ids))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
