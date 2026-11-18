import os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp()
os.environ.update(DB_ENGINE="sqlite", SQLITE_PATH=os.path.join(tmp, "t.db"), SECRET_KEY="t")
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
from datetime import datetime, timedelta
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

def found(**kw):
    h = v.get("/?" + urlencode(kw)).get_data(as_text=True)
    return h, [t for t in ALL if f"<h3>{t}</h3>" in h]

h, r = found(from_y=1445, from_m=6, from_d=1, to_y=1445, to_m=12, to_d=hu.month_length(1445, 12))
assert r == ["HD-BBB", "HD-CCC"], r; ok("range: full (inclusive both ends)")
assert '<option value="1445" selected>' in h and 'name="from_m"' in h; ok("selections kept after search")
assert f"{n_nodate} وثيقة في الأرشيف بلا تاريخ" in h; ok("notice: docs without date excluded")
h, r = found(from_y=1446, from_m=1, from_d=1); assert r == ["HD-DDD", "HD-EEE"], r; ok("from only")
h, r = found(to_y=1445, to_m=1, to_d=10); assert r == ["HD-AAA"], r; ok("to only")
h, r = found(from_y=1445, to_y=1445); assert r == ["HD-AAA", "HD-BBB", "HD-CCC"], r; ok("year only (all of 1445)")
h, r = found(from_y=1446); assert r == ["HD-DDD", "HD-EEE"], r
h, r = found(from_y=1445, from_m=6, to_y=1445, to_m=6); assert r == ["HD-BBB"], r; ok("year + month")
h, r = found(to_y=TY); assert "class=\"flash error\"" not in h and r == ALL[:5], r; ok("to current year (clamped, no error)")
h, r = found(); assert r == ALL and "بلا تاريخ" not in h; ok("no date filter: all docs, no notice")
h, r = found(from_y=1446, to_y=1445); assert "يجب ألا يكون بعد" in h and r == ALL; ok("from > to: error, filter not applied")
h, r = found(from_y=TOMORROW[0], from_m=TOMORROW[1], from_d=TOMORROW[2])
assert "flash error" in h and r == ALL; ok("future 'from' rejected")
h, r = found(to_y=TOMORROW[0], to_m=TOMORROW[1], to_d=TOMORROW[2]); assert "flash error" in h and r == ALL; ok("future 'to' rejected")
h, r = found(from_y=TY + 1); assert hu.ERR_RANGE in h and r == ALL
h, r = found(from_y=M29[0], from_m=M29[1], from_d=30); assert hu.ERR_INVALID in h and r == ALL
h, r = found(from_m=5); assert hu.ERR_PARTIAL in h and r == ALL
h, r = found(from_y="abc"); assert hu.ERR_INVALID in h and r == ALL
h, r = found(from_y="1445' OR '1'='1"); assert hu.ERR_INVALID in h and r == ALL
ok("invalid / tampered values rejected without breaking page")
h, r = found(q="HD-", cat=2, from_y=1446); assert r == ["HD-DDD"], r; ok("date + text + category")
h, r = found(cat=1, from_y=1445, to_y=1446); assert r == ["HD-AAA", "HD-BBB", "HD-EEE"], r; ok("date + category")
h, r = found(q="HD-EEE", smart=1, from_y=1446); assert r == ["HD-EEE"], r
h, r = found(q="HD-EEE", smart=1, to_y=1445); assert r == [], r; ok("date + smart search")
assert "1 محرم 1446هـ" in v.get("/").get_data(as_text=True); ok("cards show formatted Hijri date")

# --- الرفع
c = client("clerk"); tok = csrf(c)
def up(**kw):
    data = {"csrf": tok, "file": (open(f"{S}/circular_leave.png", "rb"), "u.png"), **kw}
    return c.post("/upload", data=data, content_type="multipart/form-data")
def last_doc():
    with A.app.app_context(): return db.query("SELECT * FROM documents ORDER BY id DESC LIMIT 1", one=True)
def n_docs():
    with A.app.app_context(): return db.query("SELECT COUNT(*) AS n FROM documents", one=True)["n"]
up_html = c.get("/upload").get_data(as_text=True)
assert 'name="doc_date"' not in up_html and 'name="doc_y"' in up_html and 'name="doc_m"' in up_html and 'name="doc_d"' in up_html
assert "جمادى الأولى" in up_html and f'<option value="{TY}"' in up_html and f'<option value="{TY + 1}"' not in up_html
assert '<option value="1400"' in up_html and '<option value="1399"' not in up_html; ok("upload page: Hijri picker only, years 1400..now")
assert up(title="UP1", doc_y="1446", doc_m="9", doc_d="12").status_code == 302
d = last_doc(); assert d["doc_date_h"] == "1446-09-12" and d["doc_date"] is None; ok("upload: picker saved")
assert up(title="UP2").status_code == 302 and last_doc()["doc_date_h"] is None; ok("upload: date optional")
before = n_docs()
for bad, msg in [({"doc_y": "1446"}, hu.ERR_INCOMPLETE), ({"doc_y": str(M29[0]), "doc_m": str(M29[1]), "doc_d": "30"}, hu.ERR_INVALID),
                 ({"doc_y": "1446", "doc_m": "13", "doc_d": "1"}, hu.ERR_INVALID),
                 (dict(zip(("doc_y", "doc_m", "doc_d"), map(str, TOMORROW))), None)]:
    r = up(title="BAD", **bad); t = r.get_data(as_text=True)
    assert r.status_code == 200 and "flash error" in t and (msg is None or msg in t), bad
assert n_docs() == before; ok("upload: invalid / future / partial rejected, nothing saved")
# تعبئة تلقائية من استخراج الوثيقة (نحاكي الذكاء الاصطناعي)
_ext, _gem = A.ai.extract_text, A.ai.gemini_analyze
A.ai.extract_text = lambda p, e: "تعميم\nالرقم: 77\nالتاريخ: 12/03/2025 م\nالموضوع: اختبار التحويل من الميلادي"
A.ai.gemini_analyze = lambda t, c: None
assert up(use_ai="1").status_code == 302
d = last_doc(); assert d["doc_date_h"] == "1446-09-12" and d["doc_date"] == "12/03/2025", (d["doc_date_h"], d["doc_date"])
ok("upload auto: Gregorian from document converted to Hijri")
A.ai.gemini_analyze = lambda t, c: {"title": "G", "doc_number": None, "doc_date": "12 رمضان 1446هـ", "doc_date_numeric": "1446/09/12",
                                    "source": None, "category": None, "summary": None}
assert up(use_ai="1").status_code == 302 and last_doc()["doc_date_h"] == "1446-09-12"; ok("upload auto: Gemini numeric date used")
A.ai.extract_text = lambda p, e: "تعميم بلا أي تاريخ واضح في هذا النص الطويل نسبياً"
A.ai.gemini_analyze = lambda t, c: None
assert up(use_ai="1").status_code == 302 and last_doc()["doc_date_h"] is None; ok("upload auto: no date → empty")
A.ai.extract_text = lambda p, e: "التاريخ: 1440/01/01 هـ\nالموضوع: المنتقي يتقدم على الاستخراج"
assert up(use_ai="1", doc_y="1446", doc_m="1", doc_d="1").status_code == 302 and last_doc()["doc_date_h"] == "1446-01-01"
ok("upload: picker wins over extracted date")
A.ai.extract_text, A.ai.gemini_analyze = _ext, _gem

# --- التعديل والعرض
a = client("admin"); tok = csrf(a)
with A.app.app_context():
    did = db.query("SELECT id FROM documents WHERE title='HD-NNN'", one=True)["id"]
    db.execute("UPDATE documents SET doc_date=%s WHERE id=%s", ("12/03/2025", did))
e = a.get(f"/doc/{did}/edit").get_data(as_text=True)
assert 'name="doc_date"' not in e and "التاريخ مستخرج تلقائياً من الوثيقة، يمكنك تغييره بالاختيار" in e; ok("edit page: single Hijri picker + hint")
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "HD-NNN", "doc_y": "1446", "doc_m": "9", "doc_d": "12"}).status_code == 302
with A.app.app_context(): row = db.query("SELECT doc_date, doc_date_h FROM documents WHERE id=%s", (did,), one=True)
assert row["doc_date_h"] == "1446-09-12" and row["doc_date"] == "12/03/2025"; ok("edit: picker saved, old doc_date untouched")
e = a.get(f"/doc/{did}/edit").get_data(as_text=True)
assert '<option value="1446" selected>' in e and '<option value="9" selected>' in e and '<option value="12" selected>' in e; ok("edit: picker prefilled")
r = a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "CHANGED", "doc_y": str(TOMORROW[0]), "doc_m": str(TOMORROW[1]), "doc_d": str(TOMORROW[2])})
assert r.status_code == 200 and "flash error" in r.get_data(as_text=True)
r = a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "CHANGED", "doc_y": str(M29[0]), "doc_m": str(M29[1]), "doc_d": "30"})
assert r.status_code == 200 and hu.ERR_INVALID in r.get_data(as_text=True)
with A.app.app_context(): assert db.query("SELECT title, doc_date_h FROM documents WHERE id=%s", (did,), one=True) == {"title": "HD-NNN", "doc_date_h": "1446-09-12"}
ok("edit: future / invalid rejected, nothing changed")
vw = a.get(f"/doc/{did}").get_data(as_text=True)
assert "12 رمضان 1446هـ" in vw and "النص الأصلي في الوثيقة" in vw and "12/03/2025" in vw; ok("view: Hijri date + original text note when different")
with A.app.app_context(): db.execute("UPDATE documents SET doc_date=%s WHERE id=%s", ("1446/09/12", did))
assert "النص الأصلي في الوثيقة" not in a.get(f"/doc/{did}").get_data(as_text=True); ok("view: no note when original equals Hijri date")
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "HD-NNN", "doc_y": "", "doc_m": "", "doc_d": ""}).status_code == 302
with A.app.app_context(): assert db.query("SELECT doc_date_h FROM documents WHERE id=%s", (did,), one=True)["doc_date_h"] is None
ok("edit: clearing the picker removes the date")
with A.app.app_context(): db.execute("UPDATE documents SET doc_date_h='1446-09-12' WHERE id=%s", (did,))
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "HD-NNN"}).status_code == 302
with A.app.app_context(): assert db.query("SELECT doc_date_h FROM documents WHERE id=%s", (did,), one=True)["doc_date_h"] == "1446-09-12"
ok("edit: date kept when picker not submitted")
assert "12 رمضان 1446هـ" in a.get("/dashboard").get_data(as_text=True); ok("dashboard shows Hijri date")
print("ALL TESTS PASSED")
