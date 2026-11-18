import os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp()
os.environ.update(DB_ENGINE="sqlite", SQLITE_PATH=os.path.join(tmp, "t.db"), SECRET_KEY="t", GEMINI_API_KEY="")  # بلا شبكة: Gemini بالمحاكاة فقط
import app as A, db
from werkzeug.security import generate_password_hash
db.init_sqlite()
S = os.path.join(os.path.dirname(__file__), "samples")
A.app.config["UPLOAD_FOLDER"] = tmp

with A.app.app_context():
    for u, r in [("admin", "admin"), ("clerk", "clerk"), ("viewer", "viewer")]:
        db.execute("INSERT INTO users (username, full_name, password_hash, role) VALUES (%s,%s,%s,%s)",
                   (u, u, generate_password_hash("pass123"), r))

def client(user=None):
    c = A.app.test_client()
    if user:
        tok = csrf(c)
        r = c.post("/login", data={"username": user, "password": "pass123", "csrf": tok})
        assert r.status_code == 302, r.status_code
    return c

def csrf(c):
    html = c.get("/login").get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)

ok = lambda n: print("PASS", n)

# 1) غير مسجل -> تحويل للدخول
c = A.app.test_client(); assert c.get("/").status_code == 302; ok("redirect when logged out")
# 2) دخول خاطئ
c = A.app.test_client(); r = c.post("/login", data={"username": "admin", "password": "x", "csrf": csrf(c)})
assert "غير صحيحة" in r.get_data(as_text=True); ok("bad login rejected")
# 3) CSRF
c = client("admin"); assert c.post("/categories", data={"name": "x"}).status_code == 400; ok("csrf enforced")
# 4) رفع بالذكاء الاصطناعي
c = client("clerk"); tok = csrf(c)
for f in ["circular_leave.png", "decision_exams.png"]:
    r = c.post("/upload", data={"csrf": tok, "use_ai": "1", "file": (open(f"{S}/{f}", "rb"), f)},
               content_type="multipart/form-data", follow_redirects=True)
    t = r.get_data(as_text=True)
    assert r.status_code == 200 and "تمت أرشفة" in t, t[:300]
with A.app.app_context():
    docs = db.query("SELECT d.*, c.name AS cat FROM documents d LEFT JOIN categories c ON c.id=d.category_id ORDER BY d.id")
d1, d2 = docs
print("   doc1:", d1["title"], "|", d1["doc_number"], "|", d1["doc_date"], "|", d1["cat"])
print("   doc2:", d2["title"], "|", d2["doc_number"], "|", d2["doc_date"], "|", d2["cat"])
assert d1["cat"] == "تعميم" and d2["cat"] == "قرار" and d1["doc_number"] == "4712345"; ok("AI upload: OCR + classify + fields")
assert d1["doc_date_h"] == "1447-05-12" and d2["doc_date_h"] == "1447-06-03", (d1["doc_date_h"], d2["doc_date_h"])
ok("AI upload: Hijri date filled automatically")
# 5) بحث عادي وذكي (مرادفات)
r = c.get("/?q=اجازات").get_data(as_text=True); assert "ضوابط الإجازات" in r; ok("normal search (normalization)")
r = c.get("/?q=عطلة المعلمين&smart=1").get_data(as_text=True)
assert "ضوابط الإجازات" in r and r.index("ضوابط الإجازات") >= 0; ok("smart search synonym عطلة→إجازة")
r = c.get("/?q=جدول اختبارات&smart=1").get_data(as_text=True)
assert r.index("اعتماد جدول") < (r.index("ضوابط") if "ضوابط" in r else 10**9); ok("smart search ranks best first")
# 6) عرض وتحميل
assert c.get(f"/doc/{d1['id']}").status_code == 200 and c.get(f"/file/{d1['id']}").status_code == 200; ok("view + file")
# 7) صلاحيات
assert c.get("/users").status_code == 403 and c.post(f"/doc/{d1['id']}/delete", data={"csrf": tok}).status_code == 403; ok("clerk cannot admin/delete")
v = client("viewer"); assert v.get("/upload").status_code == 403 and v.get("/").status_code == 200; ok("viewer read-only")
# 8) رفض امتداد خطير
r = c.post("/upload", data={"csrf": tok, "file": (open(f"{S}/../test_app.py", "rb"), "evil.py")}, content_type="multipart/form-data")
assert "غير مدعوم" in r.get_data(as_text=True); ok("reject .py upload")
# 9) المدير: تعديل وحذف وتصنيفات ومستخدمين
a = client("admin"); tok = csrf(a)
assert a.post(f"/doc/{d1['id']}/edit", data={"csrf": tok, "title": "عنوان معدل", "category_id": "1"}).status_code == 302; ok("edit")
assert a.post("/categories", data={"csrf": tok, "name": "تصنيف جديد"}).status_code == 302
assert a.post("/users", data={"csrf": tok, "username": "n", "full_name": "N", "password": "123456", "role": "clerk"}).status_code == 302
assert a.get("/categories").status_code == 200 and a.get("/users").status_code == 200; ok("categories+users pages")
assert a.post(f"/doc/{d2['id']}/delete", data={"csrf": tok}).status_code == 302
with A.app.app_context(): assert len(db.query("SELECT id FROM documents")) == 1
ok("delete")
# 10) open redirect
c2 = A.app.test_client(); r = c2.post("/login?next=//evil.com", data={"username": "admin", "password": "pass123", "csrf": csrf(c2)})
assert "evil.com" not in r.headers["Location"]; ok("no open redirect")
# ===================================================== 11) التاريخ الهجري
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import hijri_utils as hu, migrate_hijri
from hijri_converter import Gregorian

TODAY = hu.today_hijri()
TY, TM, TD = (int(x) for x in TODAY.split("-"))
_g = Gregorian.fromdate(datetime.now(hu.RIYADH).date() + timedelta(days=1)).to_hijri()
TOMORROW = (_g.year, _g.month, _g.day)
M29 = next((1445, m) for m in range(1, 13) if hu.month_length(1445, m) == 29)   # شهر 29 يوماً
M30 = next((1445, m) for m in range(1, 13) if hu.month_length(1445, m) == 30)   # شهر 30 يوماً

# --- دوال hijri_utils
assert len(hu.MONTHS) == 12 and hu.MONTHS[0] == "محرم" and hu.MONTHS[4] == "جمادى الأولى" and hu.MONTHS[11] == "ذو الحجة"
for txt, exp in [("2024-01-01", "1445-06-19"), ("01/01/2024", "1445-06-19"), ("2025.03.12", "1446-09-12"),
                 ("12/03/2025 م", "1446-09-12"), ("١٤٤٧/٠٥/١٢", "1447-05-12"), ("۱۴۴۷-۰۵-۱۲", "1447-05-12"),
                 ("12.05.1447", "1447-05-12"), ("12-05-1447", "1447-05-12"), ("1447/05/12 هـ", "1447-05-12"),
                 (" 1447 / 5 / 2 ", "1447-05-02"), ("‏1447/05/12‏", "1447-05-12")]:
    assert hu.parse_any_date(txt) == exp, (txt, hu.parse_any_date(txt))
ok("parse_any_date: Gregorian→Hijri, Arabic/Persian digits, separators / - .")
for txt in [f"{M29[0]}/{M29[1]}/30", "1447/13/01", "1447/00/10", "1447/05/00", "2025-02-30", "abc", "", None, "05/1447",
            "12/05/47", "1250/01/01", "1700-01-01", "2200-01-01", "1447/05/12 م", "2025/03/12 هـ", "12 جمادى 1447"]:
    assert hu.parse_any_date(txt) is None, txt
ok("parse_any_date: invalid / ambiguous → None")
assert not hu.is_valid_hijri(*M29, 30) and hu.is_valid_hijri(*M29, 29) and hu.is_valid_hijri(*M30, 30)
assert not hu.is_valid_hijri(1447, 13, 1) and not hu.is_valid_hijri(1447, 1, 0); ok("is_valid_hijri uses real month length")
assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", TODAY) and hu.split_iso(TODAY); ok("today_hijri")
assert hu.format_hijri("1447-05-12") == "12 جمادى الأولى 1447هـ" and hu.format_hijri("1446-09-01") == "1 رمضان 1446هـ"
assert hu.format_hijri(None) == "" and hu.format_hijri("1447-13-01") == "" and hu.format_hijri("x") == ""; ok("format_hijri")
assert hu.from_picker("", "", "") == (None, None)
assert hu.from_picker("1446", "9", "12") == ("1446-09-12", None)
assert hu.from_picker("1446", "", "")[1] == hu.ERR_INCOMPLETE and hu.from_picker("1399", "1", "1")[1] == hu.ERR_RANGE
assert hu.from_picker(str(M29[0]), str(M29[1]), "30")[1] == hu.ERR_INVALID and hu.from_picker("x", "1", "1")[1] == hu.ERR_INVALID
assert hu.from_picker(*map(str, TOMORROW))[1] in (hu.ERR_FUTURE, hu.ERR_RANGE)
assert hu.from_picker(TY, TM, TD) == (TODAY, None); ok("from_picker (upload/edit validation)")
assert hu.range_bound("1445", "", "", end=False) == ("1445-01-01", None)
assert hu.range_bound("1445", "", "", end=True) == (f"1445-12-{hu.month_length(1445, 12)}", None)
assert hu.range_bound(*map(str, M29), "", end=True) == (f"{M29[0]}-{M29[1]:02d}-29", None)
assert hu.range_bound(str(TY), "", "", end=True) == (TODAY, None)  # سنة حالية → تُقصّ عند اليوم
assert hu.range_bound("", "5", "", end=False)[1] == hu.ERR_PARTIAL and hu.range_bound("1445", "", "3", end=False)[1] == hu.ERR_PARTIAL
if TM < 12: assert hu.range_bound(str(TY), str(TM + 1), "", end=False)[1] == hu.ERR_FUTURE
ok("range_bound (partial year / month)")

# --- ترحيل idempotent على قاعدة قديمة بلا العمود
old = os.path.join(tmp, "old.db")
oc = sqlite3.connect(old)
oc.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT, doc_date TEXT)")
oc.executemany("INSERT INTO documents (id, title, doc_date) VALUES (?,?,?)",
               [(1, "a", "1447/05/12 هـ"), (2, "b", "2025/03/12"), (3, "c", None), (4, "d", "غير معروف"),
                (5, "e", ""), (6, "f", "١٤٤٦/٠٩/١٢"), (7, "g", f"{TY + 1}/01/01"), (8, "h", "12/03/2025")])
oc.commit()
s1 = migrate_hijri.migrate(oc, "sqlite")
assert s1["added_column"] and s1["added_index"], s1
assert s1["from_hijri"] == [1, 6] and s1["from_greg"] == [2, 8] and s1["unparsed"] == [4, 7] and s1["empty"] == [3, 5], s1
got = dict(oc.execute("SELECT id, doc_date_h FROM documents").fetchall())
assert got == {1: "1447-05-12", 2: "1446-09-12", 3: None, 4: None, 5: None, 6: "1446-09-12", 7: None, 8: "1446-09-12"}, got
oc.execute("UPDATE documents SET doc_date_h='1441-01-01' WHERE id=1")  # تعديل يدوي لاحق
oc.commit()
s2 = migrate_hijri.migrate(oc, "sqlite")
assert not s2["added_column"] and not s2["added_index"] and not s2["from_hijri"] and not s2["from_greg"], s2
assert dict(oc.execute("SELECT id, doc_date_h FROM documents").fetchall())[1] == "1441-01-01"  # لم يُكتب فوقه
assert dict(oc.execute("SELECT id, doc_date FROM documents").fetchall()) [2] == "2025/03/12"     # doc_date لم يتغير
oc.close(); ok("migration: idempotent, no overwrite, no guessing")

# --- بيانات البحث
with A.app.app_context():
    def add(title, h, cat, text=None):
        db.execute("INSERT INTO documents (title, doc_date, doc_date_h, category_id, filename, original_name, "
                   "search_text) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                   (title, text, h, cat, "x.png", "x.png", A.ai.build_search_text(title)))
    add("HD-AAA", "1445-01-10", 1)
    add("HD-BBB", "1445-06-01", 1)
    add("HD-CCC", f"1445-12-{hu.month_length(1445, 12)}", 2)
    add("HD-DDD", "1446-01-01", 2)
    add("HD-EEE", "1446-06-15", 1)
    add("HD-NNN", None, 1, "نص غامض")
    n_nodate = db.query("SELECT COUNT(*) AS n FROM documents WHERE doc_date_h IS NULL", one=True)["n"]
ALL = ["HD-AAA", "HD-BBB", "HD-CCC", "HD-DDD", "HD-EEE", "HD-NNN"]
v = client("viewer")
H = lambda y, m=None, d=None: str(y) + (f"-{m:02d}" if m else "") + (f"-{d:02d}" if d else "")

def found(**kw):
    h = v.get("/?" + urlencode(kw)).get_data(as_text=True)
    return h, [t for t in ALL if f"<h3>{t}</h3>" in h]

h, r = found(date_from=H(1445, 6, 1), date_to=H(1445, 12, hu.month_length(1445, 12)))
assert r == ["HD-BBB", "HD-CCC"], r; ok("range: full (inclusive both ends)")
assert 'name="date_from" value="1445-06-01"' in h and 'value="1 جمادى الأولى 1445هـ"' not in h
assert 'value="1 جمادى الآخرة 1445هـ"' in h; ok("selections kept after search (hidden ISO + readable text)")
assert f"{n_nodate} وثيقة في الأرشيف بلا تاريخ" in h; ok("notice: docs without date excluded")
h, r = found(date_from=H(1446, 1, 1)); assert r == ["HD-DDD", "HD-EEE"], r; ok("from only")
h, r = found(date_to=H(1445, 1, 10)); assert r == ["HD-AAA"], r; ok("to only")
h, r = found(date_from="1445", date_to="1445"); assert r == ["HD-AAA", "HD-BBB", "HD-CCC"], r; ok("year only (all of 1445)")
h, r = found(date_from="1446"); assert r == ["HD-DDD", "HD-EEE"], r
h, r = found(date_from="1445-06", date_to="1445-06"); assert r == ["HD-BBB"], r; ok("year + month")
h, r = found(date_to=str(TY)); assert "flash error" not in h and r == ALL[:5], r; ok("to current year (clamped, no error)")
h, r = found(); assert r == ALL and "بلا تاريخ" not in h; ok("no date filter: all docs, no notice")
h, r = found(date_from=H(1446, 1, 1), date_to=H(1445, 1, 1)); assert "يجب ألا يكون بعد" in h and r == ALL; ok("from > to: error, filter not applied")
h, r = found(date_from=H(*TOMORROW)); assert "flash error" in h and r == ALL; ok("future 'from' rejected")
h, r = found(date_to=H(*TOMORROW)); assert "flash error" in h and r == ALL; ok("future 'to' rejected")
h, r = found(date_from=str(TY + 1)); assert hu.ERR_RANGE in h and r == ALL
h, r = found(date_from=H(*M29, 30)); assert hu.ERR_INVALID in h and r == ALL
for bad in ["abc", "1445/06/01", "1445-06-01' OR '1'='1", "12-06-1445"]:
    h, r = found(date_from=bad); assert hu.ERR_INVALID in h and r == ALL, bad
ok("invalid / tampered values rejected without breaking page")
h, r = found(q="HD-", cat=2, date_from="1446"); assert r == ["HD-DDD"], r; ok("date + text + category")
h, r = found(cat=1, date_from="1445", date_to="1446"); assert r == ["HD-AAA", "HD-BBB", "HD-EEE"], r; ok("date + category")
h, r = found(q="HD-EEE", smart=1, date_from="1446"); assert r == ["HD-EEE"], r
h, r = found(q="HD-EEE", smart=1, date_to="1445"); assert r == [], r; ok("date + smart search")
assert "1 محرم 1446هـ" in v.get("/").get_data(as_text=True); ok("cards show formatted Hijri date")

# --- مكوّن التقويم: الحقول وجدول البيانات
import json as _json
from hijri_converter import Hijri
home = v.get("/").get_data(as_text=True)
assert 'type="hidden" name="date_from"' in home and 'type="hidden" name="date_to"' in home
assert 'data-role="to" data-pair="hdp-date_from"' in home and 'data-role="from" data-pair="hdp-date_to"' in home
assert "<select name=\"from_y\"" not in home and "hdp-text" in home and "readonly" in home and "hijri-picker.js" in home
assert v.get("/static/hijri-picker.js").status_code == 200; ok("search uses two calendar pickers (hidden ISO fields)")
cal = _json.loads(re.search(r'<script type="application/json" id="hijri-calendar-data">(.*?)</script>', home, re.S).group(1))
assert cal["min"] == 1400 and cal["today"] == TODAY and cal["months"] == hu.MONTHS
assert sorted(map(int, cal["years"])) == list(range(1400, TY + 1))
for ys, months in cal["years"].items():
    for mi, (ln, fw) in enumerate(months, 1):
        h1 = Hijri(int(ys), mi, 1)
        assert ln == h1.month_length() and fw == (h1.to_gregorian().weekday() + 1) % 7, (ys, mi, ln, fw)
assert cal["years"]["1446"][0][1] == 0 and cal["years"]["1446"][8][1] == 6  # 1 محرم 1446 أحد، 1 رمضان 1446 سبت
ok("calendar table sent to browser matches hijri-converter (month lengths + first weekday)")

# --- الرفع
c = client("clerk"); tok = csrf(c)
from PIL import Image as _Img
BLANK = os.path.join(tmp, "blank.png"); _Img.new("RGB", (600, 300), "white").save(BLANK)  # وثيقة بلا أي نص/تاريخ
def up(_file=None, **kw):
    data = {"csrf": tok, "file": (open(_file or f"{S}/circular_leave.png", "rb"), "u.png"), **kw}
    return c.post("/upload", data=data, content_type="multipart/form-data")
def last_doc():
    with A.app.app_context(): return db.query("SELECT * FROM documents ORDER BY id DESC LIMIT 1", one=True)
def n_docs():
    with A.app.app_context(): return db.query("SELECT COUNT(*) AS n FROM documents", one=True)["n"]
up_html = c.get("/upload").get_data(as_text=True)
assert 'name="doc_date"' not in up_html and 'type="hidden" name="doc_date_h" value=""' in up_html
assert 'name="doc_y"' not in up_html and "<select name=\"doc_" not in up_html and 'placeholder="اختر التاريخ"' in up_html
ok("upload page: single calendar field, no old dropdowns")
assert up(title="UP1", doc_date_h="1446-09-12").status_code == 302
d = last_doc(); assert d["doc_date_h"] == "1446-09-12" and d["doc_date_source"] == "manual" and d["updated_at"] is None, d
ok("upload: calendar value saved (YYYY-MM-DD), differs from extracted → manual")
r = up(BLANK, title="UP2", follow_redirects=True) if False else None
r = c.post("/upload", data={"csrf": tok, "title": "UP2", "file": (open(BLANK, "rb"), "b.png")}, content_type="multipart/form-data",
           follow_redirects=True)
d = last_doc(); t = r.get_data(as_text=True)
assert d["title"] == "UP2" and d["doc_date_h"] is None and d["doc_date_source"] is None and d["created_at"]
assert "لم نتمكن من تحديد تاريخ الوثيقة" in t and "/set-date" in t and "تاريخ الوثيقة</dt>" in t and "غير محدد" in t
ok("upload without any date: saved NULL (created_at NOT used), redirected to view with alert + set-date form")
before = n_docs()
for bad, msg in [("1446", hu.ERR_INCOMPLETE), (H(*M29, 30), hu.ERR_INVALID), ("1446-13-01", hu.ERR_INVALID),
                 ("12/09/1446", hu.ERR_INVALID), (H(*TOMORROW), None), ("1399-01-01", hu.ERR_RANGE)]:
    r = up(title="BAD", doc_date_h=bad); t = r.get_data(as_text=True)
    assert r.status_code == 200 and "flash error" in t and (msg is None or msg in t), bad
assert n_docs() == before; ok("upload: invalid / future / partial rejected, nothing saved")
# تعبئة تلقائية من استخراج الوثيقة (نحاكي الذكاء الاصطناعي)
_ext, _gem = A.ai.extract_text, A.ai.gemini_analyze
A.ai.extract_text = lambda p, e, **k: "تعميم\nالرقم: 77\nالتاريخ: 12/03/2025 م\nالموضوع: اختبار التحويل من الميلادي"
A.ai.gemini_analyze = lambda t, c: None
assert up(use_ai="1").status_code == 302
d = last_doc(); assert d["doc_date_h"] == "1446-09-12" and d["doc_date"].startswith("12/03/2025"), (d["doc_date_h"], d["doc_date"])
assert d["doc_date_source"] == "auto"
ok("upload auto: Gregorian from document converted to Hijri")
A.ai.gemini_analyze = lambda t, c: {"title": "G", "doc_number": None, "doc_date": "12 رمضان 1446هـ", "doc_date_numeric": "1446/09/12",
                                    "source": None, "category": None, "summary": None}
assert up(use_ai="1").status_code == 302 and last_doc()["doc_date_h"] == "1446-09-12"; ok("upload auto: Gemini numeric date used")
A.ai.extract_text = lambda p, e, **k: "تعميم بلا أي تاريخ واضح في هذا النص الطويل نسبياً"
A.ai.gemini_analyze = lambda t, c: None
assert up(use_ai="1").status_code == 302 and last_doc()["doc_date_h"] is None; ok("upload auto: no date → empty")
A.ai.extract_text = lambda p, e, **k: "التاريخ: 1440/01/01 هـ\nالموضوع: المنتقي يتقدم على الاستخراج"
assert up(use_ai="1", doc_date_h="1446-01-01").status_code == 302 and last_doc()["doc_date_h"] == "1446-01-01"
ok("upload: picker wins over extracted date")
A.ai.extract_text, A.ai.gemini_analyze = _ext, _gem

# --- التعديل والعرض
a = client("admin"); tok = csrf(a)
def doc_row(i):
    with A.app.app_context(): return db.query("SELECT * FROM documents WHERE id=%s", (i,), one=True)
def edits_of(i):
    with A.app.app_context(): return db.query("SELECT * FROM document_edits WHERE document_id=%s ORDER BY id", (i,))
with A.app.app_context():
    did = db.query("SELECT id FROM documents WHERE title='HD-NNN'", one=True)["id"]
    db.execute("UPDATE documents SET doc_date=%s WHERE id=%s", ("12/03/2025", did))
e = a.get(f"/doc/{did}/edit").get_data(as_text=True)
assert 'name="doc_date"' not in e and "التاريخ مستخرج تلقائياً من الوثيقة، يمكنك تغييره بالاختيار" in e
assert e.count('type="hidden" name="doc_date_h"') == 1; ok("edit page: single Hijri calendar field + hint")
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "HD-NNN", "doc_date_h": "1446-09-12"}).status_code == 302
row = doc_row(did); assert row["doc_date_h"] == "1446-09-12" and row["doc_date"] == "12/03/2025"; ok("edit: calendar value saved, old doc_date untouched")
e = a.get(f"/doc/{did}/edit").get_data(as_text=True)
assert 'type="hidden" name="doc_date_h" value="1446-09-12"' in e and 'value="12 رمضان 1446هـ"' in e; ok("edit: calendar prefilled")
n_logs = len(edits_of(did))
for bad, msg in [(H(*TOMORROW), None), (H(*M29, 30), hu.ERR_INVALID), ("junk", hu.ERR_INVALID)]:
    r = a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "CHANGED", "doc_date_h": bad})
    assert r.status_code == 200 and "flash error" in r.get_data(as_text=True) and (msg is None or msg in r.get_data(as_text=True))
row = doc_row(did); assert row["title"] == "HD-NNN" and row["doc_date_h"] == "1446-09-12" and len(edits_of(did)) == n_logs
ok("edit: future / invalid rejected, nothing changed or logged")
vw = a.get(f"/doc/{did}").get_data(as_text=True)
assert "12 رمضان 1446هـ" in vw and "النص الأصلي في الوثيقة" in vw and "12/03/2025" in vw; ok("view: Hijri date + original text note when different")
with A.app.app_context(): db.execute("UPDATE documents SET doc_date=%s WHERE id=%s", ("1446/09/12", did))
assert "النص الأصلي في الوثيقة" not in a.get(f"/doc/{did}").get_data(as_text=True); ok("view: no note when original equals Hijri date")
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "HD-NNN", "doc_date_h": ""}).status_code == 302
assert doc_row(did)["doc_date_h"] is None; ok("edit: clearing the calendar removes the date")
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "HD-NNN", "doc_date_h": "1446-09-12"}).status_code == 302
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "HD-NNN"}).status_code == 302
assert doc_row(did)["doc_date_h"] == "1446-09-12"; ok("edit: date kept when field not submitted")
assert "12 رمضان 1446هـ" in a.get("/dashboard").get_data(as_text=True); ok("dashboard shows Hijri date")

# ===================================================== 12) سجل التعديلات
with A.app.app_context():
    admin_id = db.query("SELECT id FROM users WHERE username='admin'", one=True)["id"]
    cats = {c["id"]: c["name"] for c in db.query("SELECT id, name FROM categories")}
    log_id = db.execute("INSERT INTO documents (title, doc_number, doc_date_h, category_id, source, description, summary, "
                        "filename, original_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        ("LOG-DOC", "11", "1446-07-05", 1, "جهة أ", "وصف قديم", "سطر1\nسطر2", "x.png", "x.png"))
form = lambda **kw: {"csrf": tok, "title": "LOG-DOC", "doc_number": "11", "doc_date_h": "1446-07-05", "category_id": "1",
                     "source": "جهة أ", "description": "وصف قديم", "summary": "سطر1\r\nسطر2", **kw}
vw = a.get(f"/doc/{log_id}").get_data(as_text=True)
assert "لم تُعدَّل منذ رفعها" in vw and "سجل التعديلات" not in vw and doc_row(log_id)["updated_at"] is None
ok("new document: updated_at NULL, 'not edited since upload'")

# بلا تغيير فعلي (حتى مع CRLF من textarea ومسافات زائدة) → لا شيء
r = a.post(f"/doc/{log_id}/edit", data=form(title="  LOG-DOC  ", source="جهة أ "), follow_redirects=True)
assert "لم تتغير أي بيانات" in r.get_data(as_text=True)
d0 = doc_row(log_id); assert d0["updated_at"] is None and d0["updated_by"] is None and edits_of(log_id) == []
ok("edit without real change: no updated_at, no log")

# عرض/تحميل/بحث لا يغيّر updated_at
for url in (f"/doc/{log_id}", f"/file/{log_id}", "/?q=LOG-DOC", f"/doc/{log_id}/edit", "/dashboard"):
    a.get(url)
assert doc_row(log_id)["updated_at"] is None; ok("view / download / search do not touch updated_at")

# تعديل التاريخ وحده → سجل بالقديم والجديد
assert a.post(f"/doc/{log_id}/edit", data=form(doc_date_h="1446-07-12")).status_code == 302
d1r = doc_row(log_id); logs = edits_of(log_id)
assert d1r["doc_date_h"] == "1446-07-12" and d1r["updated_by"] == admin_id and d1r["updated_at"]
assert len(logs) == 1 and logs[0]["user_id"] == admin_id and logs[0]["edited_at"] == d1r["updated_at"]
ch = _json.loads(logs[0]["changes"])
assert ch == [{"field": "doc_date_h", "label": "التاريخ", "old": "5 رجب 1446هـ", "new": "12 رجب 1446هـ"}], ch
ok("date-only edit: updated_at/by set, one log row with old → new (readable Hijri)")
upd = datetime.strptime(str(d1r["updated_at"])[:19], "%Y-%m-%d %H:%M:%S")
assert abs((datetime.now(timezone.utc).replace(tzinfo=None) - upd).total_seconds()) < 120; ok("updated_at stored as UTC now")
vw = a.get(f"/doc/{log_id}").get_data(as_text=True)
assert "آخر تعديل:" in vw and hu.format_riyadh(d1r["updated_at"]) in vw and "بواسطة admin" in vw
assert "<bdi>5 رجب 1446هـ</bdi> ← <bdi>12 رجب 1446هـ</bdi>" in vw and "سجل التعديلات (1)" in vw
ok("view: 'آخر تعديل' (Hijri + 12h time + user) and edit log entry")

# عدة حقول: القصيرة بالقديم والجديد (التصنيف باسمه)، والطويلة «تم تعديله» فقط
assert a.post(f"/doc/{log_id}/edit", data=form(doc_date_h="1446-07-12", title="LOG-DOC2", category_id="2",
                                               description="وصف جديد طويل", summary="ملخص آخر")).status_code == 302
logs = edits_of(log_id); assert len(logs) == 2
ch = {c["field"]: c for c in _json.loads(logs[1]["changes"])}
assert ch["title"] == {"field": "title", "label": "العنوان", "old": "LOG-DOC", "new": "LOG-DOC2"}
assert ch["category_id"]["old"] == cats[1] and ch["category_id"]["new"] == cats[2]
assert ch["description"] == {"field": "description", "label": "الملاحظات", "edited": True}
assert ch["summary"] == {"field": "summary", "label": "الملخص", "edited": True}
assert "وصف جديد" not in logs[1]["changes"] and "ملخص آخر" not in logs[1]["changes"] and set(ch) == {"title", "category_id", "description", "summary"}
vw = a.get(f"/doc/{log_id}").get_data(as_text=True)
assert vw.index("LOG-DOC2") < vw.index("سجل التعديلات") and vw.index("العنوان:") < vw.index("التاريخ:", vw.index("سجل التعديلات"))
ok("multi-field edit: short old/new (category by name), long fields only 'edited'; newest first")

# المعاملة: إن فشل تسجيل السجل لا يُحفظ التحديث
_exec = db.execute
def failing(sql, params=()):
    if sql.startswith("INSERT INTO document_edits"):
        raise RuntimeError("simulated failure")
    return _exec(sql, params)
db.execute = failing
r = a.post(f"/doc/{log_id}/edit", data=form(title="SHOULD-NOT-SAVE", category_id="2", description="وصف جديد طويل", summary="ملخص آخر"))
db.execute = _exec
assert r.status_code == 500 and doc_row(log_id)["title"] == "LOG-DOC2" and len(edits_of(log_id)) == 2
ok("transaction: update + log are atomic (rollback on failure)")

# حذف مستخدم لا يكسر السجل
assert a.post("/users", data={"csrf": tok, "username": "editor2", "full_name": "محرر مؤقت", "password": "pass123", "role": "clerk"}).status_code == 302
e2 = client("editor2"); tok2 = csrf(e2)
assert e2.post(f"/doc/{log_id}/edit", data={**form(title="LOG-DOC3", category_id="2", description="وصف جديد طويل", summary="ملخص آخر"), "csrf": tok2}).status_code == 302
with A.app.app_context(): ed_id = db.query("SELECT id FROM users WHERE username='editor2'", one=True)["id"]
assert doc_row(log_id)["updated_by"] == ed_id and "بواسطة محرر مؤقت" in a.get(f"/doc/{log_id}").get_data(as_text=True)
assert a.post(f"/users/{ed_id}/delete", data={"csrf": tok}).status_code == 302
logs = edits_of(log_id); assert len(logs) == 3 and logs[2]["user_id"] is None and doc_row(log_id)["updated_by"] is None
vw = a.get(f"/doc/{log_id}"); assert vw.status_code == 200 and "مستخدم محذوف" in vw.get_data(as_text=True)
ok("deleting a user keeps the log (user_id → NULL, shown as 'مستخدم محذوف')")

# حذف الوثيقة يحذف سجلها
assert a.post(f"/doc/{log_id}/delete", data={"csrf": tok}).status_code == 302
assert edits_of(log_id) == []; ok("deleting a document deletes its edit log (CASCADE)")

# توقيت الرياض
g1 = Gregorian(2026, 11, 18).to_hijri(); g2 = Gregorian(2026, 11, 19).to_hijri()
assert hu.format_riyadh("2026-11-18 19:32:00") == f"{hu.format_hijri(hu.to_iso(g1.year, g1.month, g1.day))} — 10:32 م"
assert hu.format_riyadh(datetime(2026, 11, 18, 21, 5)) == f"{hu.format_hijri(hu.to_iso(g2.year, g2.month, g2.day))} — 12:05 ص"
assert hu.format_riyadh("2026-11-18 09:00:00").endswith("12:00 م") and hu.format_riyadh(None) == ""
ok("format_riyadh: UTC → Riyadh (+3), Hijri date, 12h ص/م, day rollover")

# ترحيل سجل التعديلات: idempotent على قاعدة قديمة
import migrate_edit_log
oe = sqlite3.connect(os.path.join(tmp, "old_edit.db"))
oe.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT);"
                 "CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT, created_at TEXT);"
                 "INSERT INTO users VALUES (1,'u'); INSERT INTO documents VALUES (1,'a','2025-01-01 10:00:00'),(2,'b',NULL);")
m1 = migrate_edit_log.migrate(oe, "sqlite")
assert set(m1["done"]) == {"documents.updated_at", "documents.updated_by", "document_edits"} and m1["documents"] == 2 and m1["edited"] == 0, m1
m2 = migrate_edit_log.migrate(oe, "sqlite")
assert m2["done"] == [] and m2["edited"] == 0, m2
cols = {r[1] for r in oe.execute("PRAGMA table_info(documents)")}
assert {"updated_at", "updated_by"} <= cols and oe.execute("SELECT COUNT(*) FROM documents WHERE updated_at IS NULL").fetchone()[0] == 2
assert {r[1] for r in oe.execute("PRAGMA table_info(document_edits)")} == {"id", "document_id", "user_id", "edited_at", "changes"}
assert oe.execute("SELECT title, created_at FROM documents WHERE id=1").fetchone() == ("a", "2025-01-01 10:00:00")
oe.close(); ok("migration (edit log): idempotent, existing docs stay updated_at NULL, no data touched")

# ===================================================== 13) البحث بتاريخ الرفع (date_by)
# التحويل الهجري → الميلادي يطابق hijri-converter
for y in range(1400, TY + 1, 3):
    for mo in (1, 6, 12):
        for dd in (1, hu.month_length(y, mo)):
            exp = Hijri(y, mo, dd).to_gregorian()
            assert hu.hijri_to_gregorian(hu.to_iso(y, mo, dd)) == datetime(exp.year, exp.month, exp.day).date(), (y, mo, dd)
assert hu.hijri_to_gregorian("1446-09-12") == datetime(2025, 3, 12).date() and hu.hijri_to_gregorian("bad") is None
ok("hijri_to_gregorian matches hijri-converter")
# حدود يوم الرياض بتوقيت UTC (النهاية حصرية = بداية اليوم التالي)
assert hu.upload_bounds_utc("1446-09-12", "1446-09-12") == ("2025-03-11 21:00:00", "2025-03-12 21:00:00")
assert hu.upload_bounds_utc(None, None) == (None, None) and hu.upload_bounds_utc("1446-09-12", None)[1] is None
assert hu.riyadh_hijri_date("2025-03-12 20:30:00") == "1446-09-12" and hu.riyadh_hijri_date("2025-03-12 21:10:00") == "1446-09-13"
ok("upload_bounds_utc: Riyadh day → UTC range")

with A.app.app_context():
    def addu(title, created, cat, h="1440-01-01"):
        return db.execute("INSERT INTO documents (title, doc_date_h, category_id, filename, original_name, search_text, created_at) "
                          "VALUES (%s,%s,%s,%s,%s,%s,%s)", (title, h, cat, "x.png", "x.png", A.ai.build_search_text(title), created))
    addu("UPM-OLD", "2024-01-01 09:00:00", 1)        # الرياض 2024-01-01 12:00 → 19 جمادى الآخرة 1445
    addu("UPM-LATE", "2025-03-12 20:30:00", 1)       # الرياض 23:30 يوم 12 رمضان 1446
    addu("UPM-EARLY", "2025-03-12 21:10:00", 2)      # الرياض 00:10 يوم 13 رمضان 1446
    addu("UPM-LASTSEC", "2025-03-14 20:59:59", 2)    # الرياض 23:59:59 يوم 14 رمضان 1446
    addu("UPM-NEXT", "2025-03-14 21:00:00", 1)       # الرياض 00:00:00 يوم 15 رمضان 1446
    addu("UPM-NOHDATE", "2025-03-13 10:00:00", 1, None)  # بلا تاريخ وثيقة، رُفعت 13 رمضان
UPM = ["UPM-OLD", "UPM-LATE", "UPM-EARLY", "UPM-LASTSEC", "UPM-NEXT", "UPM-NOHDATE"]
def fu(**kw):
    h = v.get("/?" + urlencode(kw)).get_data(as_text=True)
    return h, [t for t in UPM if f"<h3>{t}</h3>" in h]
def order(h, names):
    return sorted(names, key=lambda t: h.index(f"<h3>{t}</h3>"))

h, r = fu(date_from="1446-09-12", date_to="1446-09-14")
assert r == [] and 'id="date-by-doc" name="date_by" value="doc" checked' in h and "من تاريخ الوثيقة" in h, r
ok("date_by absent → doc mode (current behaviour)")
h2, r2 = fu(date_from="1446-09-12", date_to="1446-09-14", date_by="xyz")
assert r2 == r and "flash error" not in h2 and 'value="doc" checked' in h2; ok("invalid date_by → doc, no error")

h, r = fu(date_from="1446-09-12", date_to="1446-09-14", date_by="upload")
assert set(r) == {"UPM-LATE", "UPM-EARLY", "UPM-LASTSEC", "UPM-NOHDATE"}, r
assert order(h, r) == ["UPM-LASTSEC", "UPM-NOHDATE", "UPM-EARLY", "UPM-LATE"], order(h, r)
ok("upload mode: full range, newest upload first")
assert 'id="date-by-upload" name="date_by" value="upload" checked' in h and "من تاريخ الرفع" in h and "إلى تاريخ الرفع" in h
assert 'name="date_from" value="1446-09-12"' in h and 'name="date_to" value="1446-09-14"' in h; ok("mode + both dates kept after search")
assert "تاريخ الأرشفة: 12 رمضان 1446هـ" in h and "تاريخ الأرشفة: 13 رمضان 1446هـ" in h; ok("cards show archive date (Riyadh day, Hijri) under its own label")
h, r = fu(date_from="1446-09-12", date_to="1446-09-12", date_by="upload"); assert r == ["UPM-LATE"], r
h, r = fu(date_from="1446-09-13", date_to="1446-09-13", date_by="upload"); assert set(r) == {"UPM-EARLY", "UPM-NOHDATE"}, r
ok("day boundary: 23:30 and 00:10 Riyadh land on their own day only")
h, r = fu(date_from="1446-09-14", date_to="1446-09-14", date_by="upload"); assert r == ["UPM-LASTSEC"], r
ok("'to' day inclusive to its last second (23:59:59), next midnight excluded")
h, r = fu(date_from="1446-09-14", date_by="upload"); assert set(r) == {"UPM-LASTSEC", "UPM-NEXT"}, r; ok("upload: from only")
h, r = fu(date_to="1446-09-12", date_by="upload"); assert set(r) == {"UPM-OLD", "UPM-LATE"}, r; ok("upload: to only")
h, r = fu(date_from="1445", date_to="1445", date_by="upload"); assert r == ["UPM-OLD"], r
h, r = fu(date_from="1446-09", date_to="1446-09", date_by="upload"); assert set(r) == set(UPM) - {"UPM-OLD"}, r; ok("upload: year only / year+month")
h, r = fu(date_from="1446-09-14", date_to="1446-09-12", date_by="upload")
assert "يجب ألا يكون بعد" in h and set(r) == set(UPM); ok("upload: from > to → error, filter not applied")
h, r = fu(date_from=H(*TOMORROW), date_by="upload"); assert "flash error" in h and set(r) == set(UPM); ok("upload: future date rejected")
h, r = fu(q="UPM-", cat=2, date_from="1446-09-12", date_to="1446-09-14", date_by="upload")
assert set(r) == {"UPM-EARLY", "UPM-LASTSEC"}, r; ok("upload: + text search + category")
h, r = fu(q="UPM-LATE", smart=1, date_from="1446-09-12", date_by="upload"); assert r == ["UPM-LATE"], r
h, r = fu(q="UPM-LATE", smart=1, date_from="1446-09-13", date_by="upload"); assert r == [], r; ok("upload: + smart search")
h, r = fu(date_from="1446-09-12", date_to="1446-09-14"); assert "بلا تاريخ،" in h and "UPM-NOHDATE" not in h
assert "تاريخ الوثيقة: <span class=\"badge-missing\">غير محدد</span>" in fu(date_by="upload")[0]
h, r = fu(date_from="1446-09-12", date_to="1446-09-14", date_by="upload"); assert "بلا تاريخ" not in h
ok("notice: shown in doc mode, hidden in upload mode (no NULL created_at)")
with A.app.app_context():
    nid = db.execute("INSERT INTO documents (title, filename, original_name, created_at) VALUES (%s,%s,%s,NULL)", ("UPM-NULLCREATED", "x.png", "x.png"))
h, r = fu(date_from="1446-09-12", date_by="upload")
assert "1 وثيقة في الأرشيف بلا تاريخ رفع" in h and "<h3>UPM-NULLCREATED</h3>" not in h; ok("NULL created_at → excluded + notice in upload mode")
with A.app.app_context(): db.execute("DELETE FROM documents WHERE id=%s", (nid,))
h, r = fu(date_by="upload"); assert set(r) == set(UPM); ok("upload mode without dates: no filter")
h = v.get("/?" + urlencode({"date_from": "1445", "date_to": "1446"})).get_data(as_text=True)
hd = [t for t in ["HD-EEE", "HD-DDD", "HD-CCC", "HD-BBB", "HD-AAA"] if f"<h3>{t}</h3>" in h]
assert sorted(hd, key=lambda t: h.index(f"<h3>{t}</h3>")) == ["HD-EEE", "HD-DDD", "HD-CCC", "HD-BBB", "HD-AAA"]; ok("doc mode with filter: newest document date first")
with A.app.app_context(): any_id = db.query("SELECT id FROM documents ORDER BY id LIMIT 1", one=True)["id"]
assert a.get(f"/doc/{any_id}").get_data(as_text=True).count("تاريخ الأرشفة") == 1; ok("view: upload date shown once (Hijri + time)")

# فهرس created_at: ترحيل idempotent
import migrate_created_index
oi = sqlite3.connect(os.path.join(tmp, "old_idx.db"))
oi.executescript("CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT, created_at TEXT);"
                 "INSERT INTO documents VALUES (1,'a','2025-01-01 10:00:00'),(2,'b',NULL);")
s1 = migrate_created_index.migrate(oi, "sqlite"); s2 = migrate_created_index.migrate(oi, "sqlite")
assert s1 == {"added_index": True, "null_created_at": 1} and s2 == {"added_index": False, "null_created_at": 1}, (s1, s2)
assert oi.execute("SELECT title, created_at FROM documents ORDER BY id").fetchall() == [("a", "2025-01-01 10:00:00"), ("b", None)]
oi.close()
mc = sqlite3.connect(os.environ["SQLITE_PATH"])
assert migrate_created_index.migrate(mc, "sqlite")["added_index"] is False; mc.close()  # المخطط الجديد فيه الفهرس
ok("migration (created_at index): idempotent, no data touched")

# ===================================================== 14) التقاط تاريخ الوثيقة
import ai as AI
_g = lambda y, m, d: (lambda h: hu.to_iso(h.year, h.month, h.day))(Gregorian(y, m, d).to_hijri())
# --- دالة الاستخراج (البديل المحلي)
cases = [
    ("تعميم\nالرقم: 4712345\nالتاريخ: 1447/05/12 هـ\nالموضوع: ضوابط", "1447-05-12"),
    ("التاريخ: 12/05/1447هـ\nنص", "1447-05-12"),
    ("التاريخ: ١٤٤٧/٠٥/١٢هـ\nالموضوع: س", "1447-05-12"),
    ("التاريخ: ۱۴۴۷-۰۵-۱۲\nنص", "1447-05-12"),
    ("المؤرخ في 1447.05.12هـ\nنص", "1447-05-12"),
    ("خطاب\nالتاريخ: 12 ربيع الأول 1447هـ\nالموضوع: اختبار", "1447-03-12"),
    ("التاريخ: ١٢ جمادى الآخرة ١٤٤٦هـ", "1446-06-12"),
    ("التاريخ: 2025/11/03م\nنص", _g(2025, 11, 3)),
    ("التاريخ: 03/11/2025\nنص", _g(2025, 11, 3)),
    ("التاريخ: 1447/05/12هـ الموافق 2025/11/04م\nنص", "1447-05-12"),               # الاثنان معاً → الهجري
    ("التاريخ: 1447/06/01هـ\nإشارة إلى خطابكم رقم 55 بتاريخ 1446/02/10هـ", "1447-06-01"),  # الإشارة لا تُختار
    ("التاريخ: 1447/05/12هـ\n" + "سطر\n" * 6 + "على أن يتم التقديم قبل 1447/06/20هـ", "1447-05-12"),  # موعد في المتن
]
for txt, exp in cases:
    r = AI.pick_document_date(txt)
    assert r["iso"] == exp and r["confidence"] == "high", (txt, r)
assert AI.pick_document_date("وزارة التعليم\n1447/05/12\nالموضوع: س")["confidence"] == "medium"
for txt, reason in [(f"التاريخ: {TY + 1}/01/01هـ", "future"), ("التاريخ: 1447/05/12هـ\nالتاريخ: 1447/06/01هـ", "ambiguous"),
                    ("نص\n" * 7 + "إشارة إلى خطابكم بتاريخ 1446/02/10هـ", "reference_only"), ("نص بلا أي تاريخ", "no_date"),
                    ("التاريخ: 12/05/47", "no_date"), ("التاريخ: 12 جمادى 1447", "no_date"), ("", "no_date"),
                    ("وزارة\n1447/05/12\n1447/06/01", "ambiguous")]:
    r = AI.pick_document_date(txt)
    assert r["iso"] is None and r["reason"] == reason, (txt, r)
ok("date extraction (regex fallback): formats, digits, month names, Gregorian→Hijri, both→Hijri, reject future/ambiguous/references")
# --- Gemini (بالمحاكاة) أولاً ثم البديل
E = AI.extract_document_date
assert E("x", {"doc_date": "12 جمادى الأولى 1447هـ", "doc_date_numeric": None, "doc_date_calendar": "hijri"})["iso"] == "1447-05-12"
assert E("x", {"doc_date": "3/11/2025", "doc_date_numeric": "2025/11/03", "doc_date_calendar": "gregorian"})["iso"] == _g(2025, 11, 3)
r = E("التاريخ: 1447/05/12هـ", {"doc_date": None, "doc_date_numeric": None}); assert r["iso"] == "1447-05-12" and r["method"] == "regex"
r = E("التاريخ: 1447/05/12هـ", {"doc_date": f"{TY + 1}/01/01هـ", "doc_date_numeric": f"{TY + 1}/01/01"}); assert r["method"] == "regex" and r["iso"] == "1447-05-12"
r = E("نص", {"doc_date": "1447/05/12", "doc_date_numeric": "2025/11/03", "doc_date_calendar": "hijri"})  # الرقمي يناقض التقويم → نأخذ النص
assert r["iso"] == "1447-05-12" and r["method"] == "gemini"
assert E("نص بلا تاريخ", None)["iso"] is None
_call, _key = AI._gemini_call, os.environ.get("GEMINI_API_KEY")
os.environ["GEMINI_API_KEY"] = "test-key"
AI._gemini_call = lambda parts, **k: _json.dumps({"title": "ع", "document_date": {"raw": "12 ربيع الأول 1447هـ", "calendar": "hijri", "numeric": "1447/03/12"}})
ga = AI.gemini_analyze("نص الوثيقة " * 5, ["تعميم"])
assert ga["doc_date"] == "12 ربيع الأول 1447هـ" and ga["doc_date_numeric"] == "1447/03/12" and ga["doc_date_calendar"] == "hijri"
AI._gemini_call = lambda parts, **k: _json.dumps({"title": "ع", "document_date": None})
assert AI.gemini_analyze("نص الوثيقة " * 5, [])["doc_date"] is None
AI._gemini_call = _call; os.environ["GEMINI_API_KEY"] = _key or ""
ok("Gemini (mocked): structured document_date parsed; validated; falls back to regex")

# --- الرفع: السبب الجذري ومسار ما قبل الحفظ
c = client("clerk"); tok = csrf(c)
_ext, _gem = A.ai.extract_text, A.ai.gemini_analyze
A.ai.extract_text = lambda p, e, **k: "تعميم\nالرقم: 4712345\nالتاريخ: 1447/05/12 هـ\nالموضوع: ضوابط الإجازات"
A.ai.gemini_analyze = lambda t, cs: {"title": "x", "doc_number": None, "doc_date": "12 جمادى الأولى 1447هـ", "doc_date_numeric": None,
                                     "doc_date_calendar": "hijri", "source": None, "category": None, "summary": "s"}
assert up(use_ai="1").status_code == 302 and last_doc()["doc_date_h"] == "1447-05-12" and last_doc()["doc_date_source"] == "auto"
A.ai.gemini_analyze = lambda t, cs: {"title": "x", "doc_number": None, "doc_date": "تاريخ غير مفهوم", "doc_date_numeric": None,
                                     "doc_date_calendar": None, "source": None, "category": None, "summary": "s"}
assert up(use_ai="1").status_code == 302 and last_doc()["doc_date_h"] == "1447-05-12"  # Gemini بلا تاريخ صالح → البديل المحلي
A.ai.extract_text, A.ai.gemini_analyze = _ext, _gem
ok("root cause fixed: Gemini date in words / unusable no longer wipes the date found locally")
A.ai.gemini_analyze = lambda *a: (_ for _ in ()).throw(AssertionError("Gemini must not be called"))
assert up().status_code == 302
d = last_doc(); assert d["doc_date_h"] == "1447-05-12" and d["doc_date_source"] == "auto" and not d["ocr_text"]
A.ai.gemini_analyze = _gem
ok("AI option unticked: date still extracted locally (no Gemini, text not stored)")

def analyze(cl, tk, fname, **kw):
    return cl.post("/upload/analyze", data={"csrf": tk, "file": (open(fname, "rb"), "a.png"), **kw}, content_type="multipart/form-data")
r = analyze(c, tok, f"{S}/circular_leave.png"); j = r.get_json()
assert r.status_code == 200 and j["doc_date_h"] == "1447-05-12" and j["doc_date_text"] == "12 جمادى الأولى 1447هـ" and re.fullmatch(r"[0-9a-f]{32}", j["token"])
pend = os.path.join(tmp, "pending"); assert os.path.exists(os.path.join(pend, j["token"] + ".png"))
before = n_docs()
r = c.post("/upload", data={"csrf": tok, "pending": j["token"], "doc_date_h": j["doc_date_h"], "title": "PEND1"})  # بلا ملف
d = last_doc(); assert r.status_code == 302 and n_docs() == before + 1 and d["title"] == "PEND1"
assert d["doc_date_h"] == "1447-05-12" and d["doc_date_source"] == "auto" and os.path.exists(os.path.join(tmp, d["filename"]))
assert not os.path.exists(os.path.join(pend, j["token"] + ".png")) and not os.path.exists(os.path.join(pend, j["token"] + ".json"))
ok("analyze before save: calendar prefilled value saved as auto, pending file moved")
j = analyze(c, tok, f"{S}/circular_leave.png").get_json()
c.post("/upload", data={"csrf": tok, "pending": j["token"], "doc_date_h": "1447-05-20", "title": "PEND2"})
assert last_doc()["doc_date_h"] == "1447-05-20" and last_doc()["doc_date_source"] == "manual"; ok("user changes prefilled date → manual")
j = analyze(c, tok, f"{S}/circular_leave.png").get_json()
c.post("/upload", data={"csrf": tok, "pending": j["token"], "doc_date_h": "", "title": "PEND3"})
assert last_doc()["doc_date_h"] == "1447-05-12" and last_doc()["doc_date_source"] == "auto"; ok("clearing the field does not wipe the extracted date")
j = analyze(c, tok, BLANK).get_json(); assert j["doc_date_h"] is None and j["token"]
cl2 = client("admin"); tk2 = csrf(cl2); before = n_docs()
r = cl2.post("/upload", data={"csrf": tk2, "pending": j["token"], "title": "STEAL"})
assert r.status_code == 200 and "اختر ملفاً" in r.get_data(as_text=True) and n_docs() == before
r = c.post("/upload", data={"csrf": tok, "pending": "../../app", "title": "X"}); assert "اختر ملفاً" in r.get_data(as_text=True)
assert client("viewer").post("/upload/analyze", data={}).status_code in (400, 403)
assert c.post("/upload/analyze", data={"file": (open(BLANK, "rb"), "b.png")}, content_type="multipart/form-data").status_code == 400
ok("pending token: only same user, validated format, CSRF + edit permission required")

# --- set-date
with A.app.app_context():
    sd = db.execute("INSERT INTO documents (title, filename, original_name, created_at) VALUES (%s,%s,%s,%s)",
                    ("SD-DOC", "x.png", "x.png", "2025-03-12 09:00:00"))
vw = c.get(f"/doc/{sd}").get_data(as_text=True)
assert "لم نتمكن من تحديد تاريخ الوثيقة" in vw and f"/doc/{sd}/set-date" in vw and "badge-missing" in vw
assert "/set-date" not in client("viewer").get(f"/doc/{sd}").get_data(as_text=True)
assert client("viewer").post(f"/doc/{sd}/set-date", data={"csrf": csrf(client('viewer'))}).status_code in (400, 403)
vv = client("viewer"); assert vv.post(f"/doc/{sd}/set-date", data={"csrf": csrf(vv), "doc_date_h": "1446-01-01"}).status_code == 403
r = c.post(f"/doc/{sd}/set-date", data={"csrf": tok, "doc_date_h": ""}, follow_redirects=True)
assert "اختر تاريخ الوثيقة" in r.get_data(as_text=True)
for bad in (H(*TOMORROW), "1446-13-01", H(*M29, 30)):
    r = c.post(f"/doc/{sd}/set-date", data={"csrf": tok, "doc_date_h": bad}, follow_redirects=True)
    assert "flash error" in r.get_data(as_text=True), bad
assert doc_row(sd)["doc_date_h"] is None and doc_row(sd)["updated_at"] is None and edits_of(sd) == []
assert c.post(f"/doc/{sd}/set-date", data={"csrf": tok, "doc_date_h": "1446-03-05"}).headers["Location"].endswith(f"/doc/{sd}")
row = doc_row(sd); logs = edits_of(sd)
with A.app.app_context(): clerk_id = db.query("SELECT id FROM users WHERE username='clerk'", one=True)["id"]
assert row["doc_date_h"] == "1446-03-05" and row["doc_date_source"] == "manual" and row["updated_at"] and row["updated_by"] == clerk_id
assert len(logs) == 1 and _json.loads(logs[0]["changes"]) == [{"field": "doc_date_h", "label": "التاريخ", "old": None, "new": "5 ربيع الأول 1446هـ"}]
assert "لم نتمكن" not in c.get(f"/doc/{sd}").get_data(as_text=True)
ok("set-date: permissions, required, future/invalid rejected, saved as manual + logged + updated_at/by")
assert c.post(f"/doc/{sd}/edit", data={"csrf": tok, "title": "SD-DOC2", "doc_date_h": "1446-03-05"}).status_code == 302
assert doc_row(sd)["doc_date_source"] == "manual"
with A.app.app_context(): db.execute("UPDATE documents SET doc_date_source='auto' WHERE id=%s", (sd,))
assert c.post(f"/doc/{sd}/edit", data={"csrf": tok, "title": "SD-DOC3", "doc_date_h": "1446-03-05"}).status_code == 302
assert doc_row(sd)["doc_date_source"] == "auto"   # العنوان فقط تغيّر → المصدر يبقى
assert c.post(f"/doc/{sd}/edit", data={"csrf": tok, "title": "SD-DOC3", "doc_date_h": "1446-03-06"}).status_code == 302
assert doc_row(sd)["doc_date_source"] == "manual"; ok("edit: changing the date marks source manual; other edits keep it")

# --- صفحة «وثائق تحتاج تاريخاً» + الروابط والأعداد
with A.app.app_context():
    sug = db.execute("INSERT INTO documents (title, filename, original_name, ocr_text) VALUES (%s,%s,%s,%s)",
                     ("SUG-DOC", "x.png", "x.png", "خطاب\nالتاريخ: 1446/04/07هـ\nالموضوع: اقتراح"))
    nos = db.execute("INSERT INTO documents (title, filename, original_name, ocr_text) VALUES (%s,%s,%s,%s)",
                     ("NOSUG-DOC", "x.png", "x.png", "نص بلا تاريخ"))
    n_missing = db.query("SELECT COUNT(*) AS n FROM documents WHERE doc_date_h IS NULL", one=True)["n"]
assert client("viewer").get("/missing-dates").status_code == 403
mp = c.get("/missing-dates").get_data(as_text=True)
assert f"وثائق تحتاج تاريخاً <span class=\"count\">{n_missing}</span>" in mp and ">SUG-DOC<" in mp and ">NOSUG-DOC<" in mp
assert 'id="hdp-d%d"' % sug in mp and 'type="hidden" name="doc_date_h" value="1446-04-07"' in mp and "مقترح" in mp
assert doc_row(sug)["doc_date_h"] is None; ok("missing-dates page: lists NULL docs, suggestion prefilled + marked, not saved until submit")
r = c.post(f"/doc/{sug}/set-date", data={"csrf": tok, "doc_date_h": "1446-04-07", "next": "missing"})
assert r.headers["Location"].endswith("/missing-dates") and doc_row(sug)["doc_date_h"] == "1446-04-07"
assert ">SUG-DOC<" not in c.get("/missing-dates").get_data(as_text=True); ok("saving from the page returns to it; row disappears")
hp_ = c.get("/").get_data(as_text=True)
assert f"وثائق تحتاج تاريخاً ({n_missing - 1})" in hp_ and "/missing-dates" in hp_
assert "/missing-dates" not in client("viewer").get("/").get_data(as_text=True)
dash = c.get("/dashboard").get_data(as_text=True); assert "وثائق تحتاج تاريخاً" in dash and f"<b>{n_missing - 1}</b>" in dash
nt = c.get("/?date_from=1446").get_data(as_text=True); assert 'href="/missing-dates">يوجد' in nt
ok("links + counts on index, dashboard; doc-mode notice links to the page (editors only)")

# --- سكربت التعبئة
import backfill_doc_dates as BF
with A.app.app_context():
    def addb(title, text, h=None):
        return db.execute("INSERT INTO documents (title, filename, original_name, ocr_text, doc_date_h) VALUES (%s,%s,%s,%s,%s)",
                          (title, "x.png", "x.png", text, h))
    b_ok = addb("BF-OK", "قرار\nالتاريخ: 1446/03/05هـ\nالموضوع: تعبئة")
    b_amb = addb("BF-AMB", "التاريخ: 1446/03/05هـ\nالتاريخ: 1446/04/01هـ")
    b_med = addb("BF-MED", "وزارة\n1446/03/05\nبلا كلمة")
    b_ref = addb("BF-REF", "نص\n" * 7 + "إشارة إلى خطابكم بتاريخ 1446/02/10هـ")
    b_none = addb("BF-NOTEXT", None)
    b_has = addb("BF-HAS", "التاريخ: 1446/09/09هـ", "1440-01-01")
def nb():
    with A.app.app_context(): return db.query("SELECT COUNT(*) AS n FROM documents WHERE doc_date_h IS NULL", one=True)["n"]
conn = sqlite3.connect(os.environ["SQLITE_PATH"]); conn.execute("PRAGMA foreign_keys = ON")
nlog = lambda: conn.execute("SELECT COUNT(*) FROM document_edits").fetchone()[0]
n0, l0 = nb(), nlog()
A.ai.gemini_analyze = lambda *a: (_ for _ in ()).throw(AssertionError("Gemini must not be called without --use-ai"))
rep = BF.backfill(conn, "sqlite")
ids = {i for i, *_ in rep["filled"]}; left = dict(rep["left"])
assert b_ok in ids and not {b_amb, b_med, b_ref, b_none, b_has} & ids, rep
assert left[b_amb] == "ambiguous" and left[b_med] == "single_in_header" and left[b_ref] == "reference_only" and left[b_none] == "no_text"
assert nb() == n0 and nlog() == l0 and doc_row(b_ok)["doc_date_h"] is None; ok("backfill dry-run: reports, writes nothing, no Gemini")
h_before = fu(date_from="1446-03-05", date_to="1446-03-05")[0]
rep = BF.backfill(conn, "sqlite", apply=True)
row = doc_row(b_ok); lg = edits_of(b_ok)
assert row["doc_date_h"] == "1446-03-05" and row["doc_date_source"] == "backfill" and row["updated_at"] is None and row["updated_by"] is None
assert len(lg) == 1 and lg[0]["user_id"] is None and _json.loads(lg[0]["changes"])[0]["note"] == "تعبئة تلقائية لتاريخ الوثيقة"
assert doc_row(b_has)["doc_date_h"] == "1440-01-01" and doc_row(b_amb)["doc_date_h"] is None and nb() == n0 - len(rep["filled"])
ok("backfill --apply: fills only high-confidence, source=backfill, logged without user, updated_at untouched, never overwrites")
rep2 = BF.backfill(conn, "sqlite", apply=True)
assert rep2["filled"] == [] and nlog() == l0 + len(rep["filled"]); ok("backfill idempotent (second run changes nothing)")
vw = c.get(f"/doc/{b_ok}").get_data(as_text=True)
assert "النظام (تعبئة تلقائية)" in vw and "(تعبئة تلقائية)" in vw and "مستخدم محذوف" not in vw; ok("view: backfill shown as system, not as deleted user")
vv = client("viewer"); hv = vv.get("/?" + urlencode({"date_from": "1446-03-05", "date_to": "1446-03-05"})).get_data(as_text=True)
assert "<h3>BF-OK</h3>" in hv and "<h3>BF-OK</h3>" not in h_before
n_before = int(re.search(r"يوجد (\d+) وثيقة في الأرشيف بلا تاريخ", h_before).group(1))
n_after = int(re.search(r"يوجد (\d+) وثيقة في الأرشيف بلا تاريخ", hv).group(1))
assert n_after == n_before - len(rep["filled"]); ok("search by document date now finds backfilled docs; excluded count drops")
A.ai.gemini_analyze = lambda t, cs: {"doc_date": "1446/04/01هـ", "doc_date_numeric": "1446/04/01", "doc_date_calendar": "hijri"}
rep3 = BF.backfill(conn, "sqlite", apply=False, use_ai=True)
assert (b_amb, "1446-04-01", "gemini") in rep3["filled"]; ok("backfill --use-ai uses Gemini (mocked) only when asked")
A.ai.gemini_analyze = _gem
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf): BF.main([])
out = buf.getvalue(); assert "تجربة فقط" in out and "تُركت للصفحة اليدوية" in out and str(b_amb) in out; ok("backfill CLI: dry-run by default, report with left IDs")
conn.close()

# --- ترحيل doc_date_source + المبدأ: لا تعبئة من created_at
import migrate_doc_date_source as MS
os_ = sqlite3.connect(os.path.join(tmp, "old_src.db")); os_.executescript("CREATE TABLE documents (id INTEGER PRIMARY KEY, doc_date_h TEXT); INSERT INTO documents VALUES (1,'1446-01-01');")
assert MS.migrate(os_, "sqlite") == {"added_column": True} and MS.migrate(os_, "sqlite") == {"added_column": False}
assert os_.execute("SELECT id, doc_date_h, doc_date_source FROM documents").fetchall() == [(1, "1446-01-01", None)]; os_.close()
ok("migration (doc_date_source): idempotent, existing rows untouched")
for fn in ("app.py", "ai.py", "hijri_utils.py", "backfill_doc_dates.py", "migrate_hijri.py", "migrate_doc_date_source.py"):
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), fn), encoding="utf-8").read()
    assert not re.search(r"doc_date_h\s*=\s*[^,\n]*created_at|created_at[^\n]*AS\s+doc_date", src), fn
ok("principle: no code fills/labels doc date from created_at")
print("ALL TESTS PASSED")
