"""نظام الوثائق والمحفوظات - إدارة التعليم بمنطقة حائل."""
import os
import secrets
import uuid
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import ai
import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
ROLES = {"admin": "مدير النظام", "clerk": "موظف أرشيف", "viewer": "مستعرض"}


def _load_env():
    path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25MB
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "uploads")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
app.teardown_appcontext(db.close_db)


# ------------------------------------------------------------ مساعدات الجلسة
@app.before_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = db.query("SELECT id, username, full_name, role FROM users WHERE id=%s", (uid,), one=True)
    if request.method == "POST":
        token = session.get("csrf")
        if not token or token != request.form.get("csrf"):
            abort(400, "رمز الحماية غير صالح، أعد تحميل الصفحة.")


@app.context_processor
def inject():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"csrf_token": session["csrf"], "ROLES": ROLES}


def login_required(roles=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                return redirect(url_for("login", next=request.path))
            if roles and g.user["role"] not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ----------------------------------------------------------------- الدخول
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db.query("SELECT * FROM users WHERE username=%s", (request.form.get("username", "").strip(),), one=True)
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            session.clear()
            session["uid"] = u["id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("index"))
        flash("اسم المستخدم أو كلمة المرور غير صحيحة", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------------------------------------- القائمة والبحث
@app.route("/")
@login_required()
def index():
    q = request.args.get("q", "").strip()
    cat = request.args.get("cat", type=int)
    smart = request.args.get("smart") == "1"
    where, params = [], []
    if cat:
        where.append("d.category_id=%s")
        params.append(cat)
    sql = ("SELECT d.id, d.title, d.doc_number, d.doc_date, d.source, d.description, d.summary, d.created_at, "
           "d.search_text, c.name AS category FROM documents d LEFT JOIN categories c ON c.id=d.category_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.id DESC"
    docs = db.query(sql, tuple(params))
    if q:
        if smart:
            docs = ai.rank(q, docs)
        else:
            qn = ai.normalize(q)
            docs = [d for d in docs if qn in ai.normalize(
                f"{d['title']} {d['doc_number'] or ''} {d['source'] or ''} {d['description'] or ''}")
                or qn in (d["search_text"] or "")]
    for d in docs:
        d.pop("search_text", None)
    cats = db.query("SELECT * FROM categories ORDER BY name")
    stats = db.query("SELECT COUNT(*) AS n FROM documents", one=True)
    return render_template("index.html", docs=docs, cats=cats, q=q, cat=cat, smart=smart, total=stats["n"])


# --------------------------------------------------------------- رفع وثيقة
@app.route("/upload", methods=["GET", "POST"])
@login_required({"admin", "clerk"})
def upload():
    cats = db.query("SELECT * FROM categories ORDER BY name")
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("اختر ملفاً للرفع", "error")
            return render_template("upload.html", cats=cats)
        if not allowed(f.filename):
            flash("نوع الملف غير مدعوم. المسموح: PDF أو صورة", "error")
            return render_template("upload.html", cats=cats)
        ext = f.filename.rsplit(".", 1)[1].lower()
        stored = f"{uuid.uuid4().hex}.{ext}"
        path = os.path.join(app.config["UPLOAD_FOLDER"], stored)
        f.save(path)

        title = request.form.get("title", "").strip()
        number = request.form.get("doc_number", "").strip()
        date = request.form.get("doc_date", "").strip()
        cat_id = request.form.get("category_id", type=int)
        source = request.form.get("source", "").strip()
        desc = request.form.get("description", "").strip()
        use_ai = request.form.get("use_ai") == "1"

        text, summary, notes = "", "", []
        if use_ai:
            text = ai.extract_text(path, ext)
            if text:
                summary = ai.summarize(text)
                fields = ai.extract_fields(text)
                gem = ai.gemini_analyze(text, [c["name"] for c in cats])
                if gem:  # Gemini أدق؛ وإن فشل نبقى على النتائج المحلية
                    summary = gem["summary"] or summary
                    for k in ("title", "doc_number", "doc_date"):
                        fields[k] = gem[k] or fields[k]
                    gcat = gem["category"]
                    notes.append("Gemini")
                elif ai.gemini_enabled():
                    flash("تعذّر الاتصال بـ Gemini، استُخدم التحليل المحلي.", "warn")
                    gcat = None
                else:
                    gcat = None
                if not title and fields["title"]:
                    title = fields["title"]; notes.append("العنوان")
                if not number and fields["doc_number"]:
                    number = fields["doc_number"]; notes.append("الرقم")
                if not date and fields["doc_date"]:
                    date = fields["doc_date"]; notes.append("التاريخ")
                if not cat_id:
                    guess = gcat or ai.classify(text, [c["name"] for c in cats])
                    cat = next((c for c in cats if c["name"] == guess), None)
                    if cat:
                        cat_id = cat["id"]; notes.append("التصنيف")
            else:
                flash("تعذّر استخراج نص من الملف، تأكد من وضوح الصورة.", "warn")
        if not title:
            title = os.path.splitext(f.filename)[0][:200] or "وثيقة بدون عنوان"

        doc_id = db.execute(
            "INSERT INTO documents (title, doc_number, doc_date, category_id, source, description, filename, "
            "original_name, ocr_text, search_text, summary, uploaded_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (title, number or None, date or None, cat_id or None, source or None, desc or None, stored,
             f.filename[:250], text, ai.build_search_text(title, number, source, desc, text), summary or None,
             g.user["id"]))
        msg = "تمت أرشفة الوثيقة بنجاح"
        if notes:
            msg += " — عبّأ الذكاء الاصطناعي: " + "، ".join(notes)
        flash(msg, "ok")
        return redirect(url_for("view", doc_id=doc_id))
    return render_template("upload.html", cats=cats)


# --------------------------------------------------------- عرض/تعديل/حذف
def get_doc(doc_id):
    d = db.query("SELECT d.*, c.name AS category, u.full_name AS uploader FROM documents d "
                 "LEFT JOIN categories c ON c.id=d.category_id LEFT JOIN users u ON u.id=d.uploaded_by "
                 "WHERE d.id=%s", (doc_id,), one=True)
    if not d:
        abort(404)
    return d


@app.route("/doc/<int:doc_id>")
@login_required()
def view(doc_id):
    d = get_doc(doc_id)
    ext = d["filename"].rsplit(".", 1)[1].lower()
    return render_template("view.html", d=d, is_pdf=(ext == "pdf"))


@app.route("/file/<int:doc_id>")
@login_required()
def file(doc_id):
    d = get_doc(doc_id)
    dl = request.args.get("dl") == "1"
    return send_from_directory(app.config["UPLOAD_FOLDER"], d["filename"], as_attachment=dl,
                               download_name=d["original_name"] if dl else None)


@app.route("/doc/<int:doc_id>/edit", methods=["GET", "POST"])
@login_required({"admin", "clerk"})
def edit(doc_id):
    d = get_doc(doc_id)
    cats = db.query("SELECT * FROM categories ORDER BY name")
    if request.method == "POST":
        f = request.form
        title = f.get("title", "").strip() or d["title"]
        number, source, desc = f.get("doc_number", "").strip(), f.get("source", "").strip(), f.get("description", "").strip()
        db.execute("UPDATE documents SET title=%s, doc_number=%s, doc_date=%s, category_id=%s, source=%s, "
                   "description=%s, summary=%s, search_text=%s WHERE id=%s",
                   (title, number or None, f.get("doc_date", "").strip() or None, f.get("category_id", type=int),
                    source or None, desc or None, f.get("summary", "").strip() or None,
                    ai.build_search_text(title, number, source, desc, d["ocr_text"] or ""), doc_id))
        flash("تم حفظ التعديلات", "ok")
        return redirect(url_for("view", doc_id=doc_id))
    return render_template("edit.html", d=d, cats=cats)


@app.route("/doc/<int:doc_id>/delete", methods=["POST"])
@login_required({"admin"})
def delete(doc_id):
    d = get_doc(doc_id)
    db.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
    try:
        os.remove(os.path.join(app.config["UPLOAD_FOLDER"], d["filename"]))
    except OSError:
        pass
    flash("تم حذف الوثيقة", "ok")
    return redirect(url_for("index"))


# --------------------------------------------------------- التصنيفات (مدير)
@app.route("/categories", methods=["GET", "POST"])
@login_required({"admin"})
def categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            try:
                db.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
                flash("تمت إضافة التصنيف", "ok")
            except Exception:
                flash("التصنيف موجود مسبقاً", "error")
        return redirect(url_for("categories"))
    cats = db.query("SELECT c.id, c.name, COUNT(d.id) AS n FROM categories c "
                    "LEFT JOIN documents d ON d.category_id=c.id GROUP BY c.id, c.name ORDER BY c.name")
    return render_template("categories.html", cats=cats)


@app.route("/categories/<int:cid>/delete", methods=["POST"])
@login_required({"admin"})
def category_delete(cid):
    db.execute("UPDATE documents SET category_id=NULL WHERE category_id=%s", (cid,))
    db.execute("DELETE FROM categories WHERE id=%s", (cid,))
    flash("تم حذف التصنيف", "ok")
    return redirect(url_for("categories"))


# ----------------------------------------------------------- المستخدمون (مدير)
@app.route("/users", methods=["GET", "POST"])
@login_required({"admin"})
def users():
    if request.method == "POST":
        f = request.form
        username, name, pw, role = f.get("username", "").strip(), f.get("full_name", "").strip(), f.get("password", ""), f.get("role")
        if not (username and name and len(pw) >= 6 and role in ROLES):
            flash("أكمل الحقول (كلمة المرور 6 أحرف على الأقل)", "error")
        else:
            try:
                db.execute("INSERT INTO users (username, full_name, password_hash, role) VALUES (%s,%s,%s,%s)",
                           (username, name, generate_password_hash(pw), role))
                flash("تمت إضافة المستخدم", "ok")
            except Exception:
                flash("اسم المستخدم موجود مسبقاً", "error")
        return redirect(url_for("users"))
    return render_template("users.html", users=db.query("SELECT id, username, full_name, role FROM users ORDER BY id"))


@app.route("/users/<int:uid>/delete", methods=["POST"])
@login_required({"admin"})
def user_delete(uid):
    if uid == g.user["id"]:
        flash("لا يمكنك حذف حسابك", "error")
    else:
        db.execute("DELETE FROM users WHERE id=%s", (uid,))
        flash("تم حذف المستخدم", "ok")
    return redirect(url_for("users"))


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, msg="ليس لديك صلاحية لهذه الصفحة"), 403


@app.errorhandler(404)
def notfound(_e):
    return render_template("error.html", code=404, msg="الصفحة غير موجودة"), 404


@app.errorhandler(400)
def badreq(e):
    return render_template("error.html", code=400, msg=getattr(e, "description", "طلب غير صالح")), 400


if __name__ == "__main__":
    if db.ENGINE == "sqlite":
        db.init_sqlite()
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", host="0.0.0.0", port=5000)
