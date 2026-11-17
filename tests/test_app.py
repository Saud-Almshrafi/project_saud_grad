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
print("ALL TESTS PASSED")
