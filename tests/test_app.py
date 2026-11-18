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
# 11) ---- البحث بين تاريخين ----
import sqlite3
from datetime import date, timedelta
import dates, migrate_date_greg

TODAY = date.today()
# دوال تحليل التاريخ: المقبول
for txt, exp in [("2025-03-12", "2025-03-12"), ("2025/03/12", "2025-03-12"), ("12/03/2025", "2025-03-12"),
                 ("12-03-2025", "2025-03-12"), ("٢٠٢٥/٠٣/١٢", "2025-03-12"), ("2025/3/2", "2025-03-02"),
                 ("12/03/2025 م", "2025-03-12"), (" 1900-01-01 ", "1900-01-01")]:
    assert dates.clear_gregorian(txt) == exp, (txt, dates.clear_gregorian(txt))
# المرفوض (هجري / غامض / غير صالح / مستقبلي / خارج النطاق)
for txt in ["1447/05/12", "1447/05/12 هـ", "12/05/1447 هـ", "2025/13/01", "31/02/2025", "1899-12-31", "05/2025",
            "12 مارس 2025", "", None, "abc", (TODAY + timedelta(days=1)).isoformat(), "2025-03-12 هـ"]:
    assert dates.clear_gregorian(txt) is None, txt
assert dates.clear_gregorian(TODAY.isoformat()) == TODAY.isoformat()
# منتقي التاريخ
assert dates.parse_form_date("") == (None, None) and dates.parse_form_date(None) == (None, None)
assert dates.parse_form_date("2025-03-12") == ("2025-03-12", None)
assert dates.parse_form_date("2025-13-45")[1] == dates.ERR_FORMAT and dates.parse_form_date("abc")[1] == dates.ERR_FORMAT
assert dates.parse_form_date("12/03/2025")[1] == dates.ERR_FORMAT and dates.parse_form_date("1800-01-01")[1] == dates.ERR_FORMAT
assert dates.parse_form_date((TODAY + timedelta(days=1)).isoformat())[1] == dates.ERR_FUTURE
assert dates.parse_form_date(TODAY.isoformat()) == (TODAY.isoformat(), None)
ok("date parsing helpers")

# ترحيل: قاعدة قديمة بدون العمود، يُشغَّل مرتين
old = os.path.join(tmp, "old.db")
oc = sqlite3.connect(old)
oc.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT, doc_date TEXT)")
oc.executemany("INSERT INTO documents (id, title, doc_date) VALUES (?,?,?)",
               [(1, "a", "2025/03/12"), (2, "b", "1447/05/12 هـ"), (3, "c", None), (4, "d", "12/03/2025"),
                (5, "e", "غير معروف"), (6, "f", "")])
oc.commit()
s1 = migrate_date_greg.migrate(oc, "sqlite")
assert s1["added_column"] and s1["added_index"] and s1["migrated"] == 2 and s1["left_null"] == 2 and s1["no_date_text"] == 2, s1
s2 = migrate_date_greg.migrate(oc, "sqlite")
assert not s2["added_column"] and not s2["added_index"] and s2["migrated"] == 0 and s2["left_null"] == 2, s2
got = dict(oc.execute("SELECT id, doc_date_greg FROM documents").fetchall())
assert got == {1: "2025-03-12", 2: None, 3: None, 4: "2025-03-12", 5: None, 6: None}, got
assert dict(oc.execute("SELECT id, doc_date FROM documents").fetchall())[2] == "1447/05/12 هـ"  # doc_date لم يتغير
oc.close(); ok("migration (idempotent, no guessing Hijri)")

# بيانات الفلتر (إدخال مباشر بدون الذكاء الاصطناعي)
with A.app.app_context():
    def add(title, greg, cat, text=None):
        db.execute("INSERT INTO documents (title, doc_date, doc_date_greg, category_id, filename, original_name, "
                   "search_text) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                   (title, text, greg, cat, "x.png", "x.png", A.ai.build_search_text(title)))
    add("DR-JAN", "2025-01-10", 1)
    add("DR-FEBA", "2025-02-01", 1)
    add("DR-FEBB", "2025-02-15", 2)
    add("DR-MAR31", "2025-03-31", 2)
    add("DR-APR", "2025-04-01", 1)
    add("DR-NODATE", None, 1, "1447/05/12 هـ")
    n_nogreg = db.query("SELECT COUNT(*) AS n FROM documents WHERE doc_date_greg IS NULL", one=True)["n"]
ALL = ["DR-JAN", "DR-FEBA", "DR-FEBB", "DR-MAR31", "DR-APR", "DR-NODATE"]
v = client("viewer")

def found(url):
    h = v.get(url).get_data(as_text=True)
    return h, [t for t in ALL if f"<h3>{t}</h3>" in h]  # عناوين البطاقات فقط (لا قيمة حقل البحث)

h, r = found("/?date_from=2025-02-01&date_to=2025-03-31")
assert r == ["DR-FEBA", "DR-FEBB", "DR-MAR31"], r; ok("range (inclusive both ends)")
assert 'value="2025-02-01"' in h and 'value="2025-03-31"' in h; ok("date inputs keep their values")
assert f"{n_nogreg} وثيقة في الأرشيف ليس لها تاريخ ميلادي" in h; ok("notice: docs without Gregorian date")
h, r = found("/?date_from=2025-03-31"); assert r == ["DR-MAR31", "DR-APR"], r; ok("from only")
h, r = found("/?date_to=2025-01-10"); assert r == ["DR-JAN"], r; ok("to only")
h, r = found("/"); assert r == ALL and "ليس لها تاريخ ميلادي" not in h; ok("no date filter (all docs, no notice)")
h, r = found("/?date_from=&date_to="); assert r == ALL; ok("empty date params ignored")
h, r = found("/?date_from=2025-04-01&date_to=2025-01-01")
assert "يجب ألا يكون بعد" in h and r == ALL; ok("from > to: error and filter not applied")
tomorrow = (TODAY + timedelta(days=1)).isoformat()
h, r = found(f"/?date_from={tomorrow}"); assert "في المستقبل" in h and r == ALL; ok("future date rejected")
h, r = found(f"/?date_to={tomorrow}"); assert "في المستقبل" in h and r == ALL; ok("future 'to' rejected")
for bad in ["2025-13-45", "abc", "12/03/2025", "'; DROP TABLE documents;--"]:
    resp = v.get("/?date_from=" + bad)
    assert resp.status_code == 200 and "غير صالحة" in resp.get_data(as_text=True), bad
with A.app.app_context(): assert db.query("SELECT COUNT(*) AS n FROM documents", one=True)["n"] >= 7
ok("invalid format rejected without breaking page")
h, r = found("/?q=DR-FEB&date_from=2025-02-10&date_to=2025-12-31"); assert r == ["DR-FEBB"], r; ok("date + text search")
h, r = found("/?cat=1&date_from=2025-01-01&date_to=2025-12-31"); assert r == ["DR-JAN", "DR-FEBA", "DR-APR"], r; ok("date + category")
h, r = found("/?q=DR-MAR31&smart=1&date_from=2025-03-01&date_to=2025-03-31"); assert r == ["DR-MAR31"], r
h, r = found("/?q=DR-MAR31&smart=1&date_from=2025-04-01"); assert r == [], r; ok("date + smart search")
h, r = found("/?q=DR-&cat=2&date_from=2025-03-01&date_to=2025-03-31"); assert r == ["DR-MAR31"], r; ok("date + text + category")

# رفع: منتقي / اشتقاق من النص / هجري / مستقبلي
c = client("clerk"); tok = csrf(c)
def up(**kw):
    data = {"csrf": tok, "file": (open(f"{S}/circular_leave.png", "rb"), "u.png"), **kw}
    return c.post("/upload", data=data, content_type="multipart/form-data")
def last_doc():
    with A.app.app_context(): return db.query("SELECT * FROM documents ORDER BY id DESC LIMIT 1", one=True)
assert up(doc_date_greg="2025-05-05", title="UP1").status_code == 302
assert str(last_doc()["doc_date_greg"])[:10] == "2025-05-05"; ok("upload: date picker saved")
assert up(doc_date="05/06/2025", title="UP2").status_code == 302
d = last_doc(); assert str(d["doc_date_greg"])[:10] == "2025-06-05" and d["doc_date"] == "05/06/2025"; ok("upload: derived from clear Gregorian text")
assert up(doc_date="1447/05/12 هـ", title="UP3").status_code == 302
d = last_doc(); assert d["doc_date_greg"] is None and d["doc_date"] == "1447/05/12 هـ"; ok("upload: Hijri text left NULL")
assert up(doc_date="2025/01/01", doc_date_greg="2025-07-07", title="UP4").status_code == 302
assert str(last_doc()["doc_date_greg"])[:10] == "2025-07-07"; ok("upload: picker wins over text")
with A.app.app_context(): before = db.query("SELECT COUNT(*) AS n FROM documents", one=True)["n"]
r = up(doc_date_greg=tomorrow, title="UP5")
assert r.status_code == 200 and "في المستقبل" in r.get_data(as_text=True)
r = up(doc_date_greg="2025-99-99", title="UP6"); assert r.status_code == 200 and "غير صالحة" in r.get_data(as_text=True)
with A.app.app_context(): assert db.query("SELECT COUNT(*) AS n FROM documents", one=True)["n"] == before
ok("upload: invalid/future date rejected, nothing saved")

# تعديل
a = client("admin"); tok = csrf(a)
with A.app.app_context(): did = db.query("SELECT id FROM documents WHERE title='DR-NODATE'", one=True)["id"]
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "DR-NODATE", "doc_date": "1447/05/12 هـ"}).status_code == 302
with A.app.app_context(): assert db.query("SELECT doc_date_greg FROM documents WHERE id=%s", (did,), one=True)["doc_date_greg"] is None
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "DR-NODATE", "doc_date_greg": "2025-08-08"}).status_code == 302
with A.app.app_context(): assert str(db.query("SELECT doc_date_greg FROM documents WHERE id=%s", (did,), one=True)["doc_date_greg"])[:10] == "2025-08-08"
assert a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "DR-NODATE", "doc_date": "20/09/2025"}).status_code == 302
with A.app.app_context(): assert str(db.query("SELECT doc_date_greg FROM documents WHERE id=%s", (did,), one=True)["doc_date_greg"])[:10] == "2025-09-20"
r = a.post(f"/doc/{did}/edit", data={"csrf": tok, "title": "x", "doc_date_greg": tomorrow})
assert r.status_code == 200 and "في المستقبل" in r.get_data(as_text=True)
with A.app.app_context(): assert db.query("SELECT title FROM documents WHERE id=%s", (did,), one=True)["title"] == "DR-NODATE"
assert 'value="2025-09-20"' in a.get(f"/doc/{did}/edit").get_data(as_text=True)
ok("edit: picker / derive / future rejected / prefilled")

# عرض
assert "2025-09-20" in a.get(f"/doc/{did}").get_data(as_text=True) and "التاريخ الميلادي" in a.get(f"/doc/{did}").get_data(as_text=True)
assert "ميلادي: 2025-09-20" in a.get("/?date_from=2025-09-01").get_data(as_text=True)
ok("view + cards show Gregorian date")
print("ALL TESTS PASSED")
