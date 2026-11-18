"""نظام الوثائق والمحفوظات - إدارة التعليم بمنطقة حائل."""
import json
import os
import secrets
import uuid
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import ai
import db
import hijri_utils as hu

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


@app.template_filter("hijri")
def _hijri_filter(s):
    return hu.format_hijri(s)


@app.template_filter("riyadh")
def _riyadh_filter(v):
    return hu.format_riyadh(v)


def render_with_picker(tpl, **kw):
    """صفحة فيها مكوّن التقويم الهجري: نرسل معها جدول التقويم المحسوب في الخادم."""
    return render_template(tpl, HIJRI=hu.calendar_data(), **kw)


def picked_date(value, **kw):
    """قيمة الحقل المخفي للتقويم ('YYYY-MM-DD' هجري) → (iso, None) أو (None, None) أو (None, خطأ)."""
    parts = hu.split_parts(value)
    if parts is None:
        return None, hu.ERR_INVALID
    return hu.from_picker(*parts, **kw)


def picked_bound(value, end, today):
    parts = hu.split_parts(value)
    if parts is None:
        return None, hu.ERR_INVALID
    return hu.range_bound(*parts, end=end, today=today)


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


# ------------------------------------------------------------- لوحة المعلومات
_DASH_COLORS = ["#0f6b4f", "#2e9e7a", "#c9a227", "#3b82a0", "#8e5ea2", "#c0392b", "#6a7a73", "#d98e04"]


@app.route("/dashboard")
@login_required()
def dashboard():
    rows = db.query(
        "SELECT c.id, c.name, COUNT(d.id) AS cnt FROM categories c "
        "LEFT JOIN documents d ON d.category_id=c.id GROUP BY c.id, c.name ORDER BY cnt DESC, c.name")
    none = db.query("SELECT COUNT(*) AS n FROM documents WHERE category_id IS NULL", one=True)["n"]
    if none:
        rows.append({"id": None, "name": "بدون تصنيف", "cnt": none})
    total = sum(r["cnt"] for r in rows)
    top = max((r["cnt"] for r in rows), default=0)
    stops, acc = [], 0
    for i, r in enumerate(rows):
        r["color"] = _DASH_COLORS[i % len(_DASH_COLORS)]
        r["pct"] = round(r["cnt"] * 100 / total, 1) if total else 0
        r["bar"] = round(r["cnt"] * 100 / top) if top else 0
        if r["cnt"]:
            stops.append(f"{r['color']} {acc}% {acc + r['pct']}%")
            acc += r["pct"]
    donut = "conic-gradient(" + ", ".join(stops) + ")" if stops else "#e6ece9"
    recent = db.query(
        "SELECT d.id, d.title, d.doc_date_h, d.created_at, c.name AS category FROM documents d "
        "LEFT JOIN categories c ON c.id=d.category_id ORDER BY d.id DESC LIMIT 5")
    return render_template("dashboard.html", rows=rows, total=total, donut=donut, recent=recent)


# -------------------------------------------------------- القائمة والبحث
@app.route("/")
@login_required()
def index():
    q = request.args.get("q", "").strip()
    cat = request.args.get("cat", type=int)
    smart = request.args.get("smart") == "1"
    f_from, f_to = request.args.get("date_from", "").strip(), request.args.get("date_to", "").strip()
    today = hu.today_hijri()
    d_from, err_from = picked_bound(f_from, end=False, today=today)
    d_to, err_to = picked_bound(f_to, end=True, today=today)
    for err, label in ((err_from, "من"), (err_to, "إلى")):
        if err:
            flash(f"تاريخ «{label}»: {err}", "error")
    if err_from or err_to:
        d_from = d_to = None  # أي خطأ → لا يُطبَّق فلتر التاريخ
    elif d_from and d_to and d_from > d_to:
        flash("تاريخ «من» يجب ألا يكون بعد تاريخ «إلى»، لم يُطبَّق فلتر التاريخ.", "error")
        d_from = d_to = None
    where, params = [], []
    if cat:
        where.append("d.category_id=%s")
        params.append(cat)
    if d_from:  # مقارنة نصية صحيحة لأن الصيغة منتظمة YYYY-MM-DD
        where.append("d.doc_date_h>=%s")
        params.append(d_from)
    if d_to:
        where.append("d.doc_date_h<=%s")
        params.append(d_to)
    sql = ("SELECT d.id, d.title, d.doc_number, d.doc_date_h, d.source, d.description, d.summary, d.created_at, "
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
    no_date = None
    if d_from or d_to:  # الوثائق بلا تاريخ تُستبعد عند الفلتر
        no_date = db.query("SELECT COUNT(*) AS n FROM documents WHERE doc_date_h IS NULL", one=True)["n"]
    # نعيد للمكوّن القيمة الكاملة فقط (القيم الجزئية من الروابط تبقى في الفلتر لكن لا تُعرض في الخانة)
    show = lambda v: v if hu.split_iso(v) else ""
    return render_with_picker("index.html", docs=docs, cats=cats, q=q, cat=cat, smart=smart, total=stats["n"],
                              f_from=show(f_from), f_to=show(f_to), no_date=no_date)


# --------------------------------------------------------------- رفع وثيقة
@app.route("/upload", methods=["GET", "POST"])
@login_required({"admin", "clerk"})
def upload():
    cats = db.query("SELECT * FROM categories ORDER BY name")
    pick = request.form.get("doc_date_h", "").strip()
    keep = pick if hu.split_iso(pick) else ""  # نعيد عرض التاريخ الصالح فقط بعد خطأ
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("اختر ملفاً للرفع", "error")
            return render_with_picker("upload.html", cats=cats, pick=keep)
        if not allowed(f.filename):
            flash("نوع الملف غير مدعوم. المسموح: PDF أو صورة", "error")
            return render_with_picker("upload.html", cats=cats, pick=keep)
        today = hu.today_hijri()
        date_h, date_err = picked_date(pick, today=today)
        if date_err:  # نتحقق قبل حفظ الملف حتى لا يبقى ملف يتيم على القرص
            flash(f"التاريخ: {date_err}", "error")
            return render_with_picker("upload.html", cats=cats, pick=keep)
        ext = f.filename.rsplit(".", 1)[1].lower()
        stored = f"{uuid.uuid4().hex}.{ext}"
        path = os.path.join(app.config["UPLOAD_FOLDER"], stored)
        f.save(path)

        title = request.form.get("title", "").strip()
        number = request.form.get("doc_number", "").strip()
        date = ""  # النص الأصلي للتاريخ كما استخرجه الذكاء الاصطناعي (يُحفظ في doc_date للأرشيف فقط)
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
                date_numeric = gem["doc_date_numeric"] if gem else None
                if gem:  # Gemini أدق؛ وإن فشل نبقى على النتائج المحلية
                    summary = gem["summary"] or summary
                    for k in ("title", "doc_number", "doc_date", "source"):
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
                date = fields["doc_date"] or ""
                if not date_h:  # القوائم فارغة: نعبّئ من الوثيقة (الميلادي يُحوَّل لهجري، والغامض يُترك)
                    auto = hu.parse_any_date(date_numeric) or hu.parse_any_date(date)
                    if auto and auto <= today:
                        date_h = auto; notes.append("التاريخ")
                if not source and fields["source"]:
                    source = fields["source"][:150]; notes.append("الجهة")
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
            "INSERT INTO documents (title, doc_number, doc_date, doc_date_h, category_id, source, description, "
            "filename, original_name, ocr_text, search_text, summary, uploaded_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (title, number or None, date[:20] or None, date_h, cat_id or None, source or None, desc or None, stored,
             f.filename[:250], text, ai.build_search_text(title, number, source, desc, text), summary or None,
             g.user["id"]))
        msg = "تمت أرشفة الوثيقة بنجاح"
        if notes:
            msg += " — عبّأ الذكاء الاصطناعي: " + "، ".join(notes)
        flash(msg, "ok")
        return redirect(url_for("view", doc_id=doc_id))
    return render_with_picker("upload.html", cats=cats, pick=keep)


# --------------------------------------------------------- عرض/تعديل/حذف
def get_doc(doc_id):
    d = db.query("SELECT d.*, c.name AS category, u.full_name AS uploader, ub.full_name AS updater FROM documents d "
                 "LEFT JOIN categories c ON c.id=d.category_id LEFT JOIN users u ON u.id=d.uploaded_by "
                 "LEFT JOIN users ub ON ub.id=d.updated_by WHERE d.id=%s", (doc_id,), one=True)
    if not d:
        abort(404)
    return d


# الحقول التي تُقارن عند التعديل: (العمود، التسمية، قصير؟). القصير يُسجَّل قديمه وجديده، والطويل يُسجَّل أنه عُدِّل فقط.
EDIT_FIELDS = [("title", "العنوان", True), ("doc_number", "رقم الوثيقة", True), ("doc_date_h", "التاريخ", True),
               ("category_id", "التصنيف", True), ("source", "الجهة", True),
               ("description", "الملاحظات", False), ("summary", "الملخص", False)]


def _norm(v):
    """توحيد للمقارنة: None/فارغ متساويان، وأسطر textarea (CRLF) مثل المخزّنة (LF)، بلا مسافات طرفية."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    v = str(v).replace("\r\n", "\n").strip()
    return v or None


def diff_document(old: dict, new: dict, cat_names: dict) -> list[dict]:
    """يقارن القيم القديمة بالجديدة ويرجع قائمة التغييرات (فارغة إن لم يتغير شيء فعلياً)."""
    shown = {"doc_date_h": lambda v: hu.format_hijri(v) or None,
             "category_id": lambda v: cat_names.get(v) if v is not None else None}
    changes = []
    for col, label, short in EDIT_FIELDS:
        a, b = _norm(old.get(col)), _norm(new.get(col))
        if a == b:
            continue
        if short:
            fmt = shown.get(col, lambda v: v)
            changes.append({"field": col, "label": label, "old": fmt(a), "new": fmt(b)})
        else:
            changes.append({"field": col, "label": label, "edited": True})
    return changes


@app.route("/doc/<int:doc_id>")
@login_required()
def view(doc_id):
    d = get_doc(doc_id)
    ext = d["filename"].rsplit(".", 1)[1].lower()
    # النص القديم يُعرض كملاحظة فقط إن اختلف عن التاريخ المعتمد (ليس هو نفسه مكتوباً هجرياً)
    orig = (d.get("doc_date") or "").strip()
    show_orig = bool(orig) and hu.parse_any_date_kind(orig) != ((d.get("doc_date_h"), "h") if d.get("doc_date_h") else None)
    edits = db.query("SELECT e.id, e.edited_at, e.changes, u.full_name AS editor FROM document_edits e "
                     "LEFT JOIN users u ON u.id=e.user_id WHERE e.document_id=%s "
                     "ORDER BY e.edited_at DESC, e.id DESC", (doc_id,))
    for e in edits:
        try:
            e["changes"] = json.loads(e["changes"] or "[]")
        except ValueError:
            e["changes"] = []
    # العرض للقراءة فقط: لا يغيّر updated_at
    return render_template("view.html", d=d, is_pdf=(ext == "pdf"), orig_date=orig if show_orig else None, edits=edits)


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
        if "doc_date_h" not in f:  # المكوّن لم يُرسل أصلاً → لا نغيّر التاريخ
            date_h, date_err = d.get("doc_date_h"), None
        else:
            date_h, date_err = picked_date(f.get("doc_date_h"))
        if date_err:
            flash(f"التاريخ: {date_err}", "error")
            return render_with_picker("edit.html", d=d, cats=cats, pick=d.get("doc_date_h") or "")
        new = {"title": _norm(f.get("title")) or d["title"], "doc_number": _norm(f.get("doc_number")),
               "doc_date_h": date_h, "category_id": f.get("category_id", type=int), "source": _norm(f.get("source")),
               "description": _norm(f.get("description")), "summary": _norm(f.get("summary"))}
        changes = diff_document(d, new, {c["id"]: c["name"] for c in cats})
        if not changes:  # لا تغيير فعلي: لا نلمس updated_at ولا نسجّل شيئاً
            flash("لم تتغير أي بيانات.", "ok")
            return redirect(url_for("view", doc_id=doc_id))
        now = hu.utc_now_str()
        # التحديث والسجل معاً أو لا شيء. doc_date القديم لا يُلمس: يبقى أرشيفاً للنص الأصلي
        with db.transaction():
            db.execute("UPDATE documents SET title=%s, doc_number=%s, doc_date_h=%s, category_id=%s, source=%s, "
                       "description=%s, summary=%s, search_text=%s, updated_at=%s, updated_by=%s WHERE id=%s",
                       (new["title"], new["doc_number"], new["doc_date_h"], new["category_id"], new["source"],
                        new["description"], new["summary"],
                        ai.build_search_text(new["title"], new["doc_number"] or "", new["source"] or "",
                                             new["description"] or "", d["ocr_text"] or ""),
                        now, g.user["id"], doc_id))
            db.execute("INSERT INTO document_edits (document_id, user_id, edited_at, changes) VALUES (%s,%s,%s,%s)",
                       (doc_id, g.user["id"], now, json.dumps(changes, ensure_ascii=False)))
        flash("تم حفظ التعديلات: " + "، ".join(c["label"] for c in changes), "ok")
        return redirect(url_for("view", doc_id=doc_id))
    return render_with_picker("edit.html", d=d, cats=cats, pick=d.get("doc_date_h") or "")


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
