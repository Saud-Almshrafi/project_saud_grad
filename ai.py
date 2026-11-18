
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter

# ---------------------------------------------------------------- تطبيع عربي
_TASHKEEL = re.compile(r"[ً-ْـ]")  # التشكيل + التطويل
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

STOPWORDS = set("""
في من الى إلى على عن مع هذا هذه ذلك تلك هو هي هم ان أن إن أنه انه التي الذي الذين
كما او أو ثم قد لا ما لم لن كان كانت يكون تكون بعد قبل بين حتى عند كل بعض غير
وذلك وقد وان وإن لدى لدي حيث اذا إذا اي أي نحو خلال منذ عليه عليها له لها به بها
ورقم رقم تاريخ التاريخ الموضوع المرفقات سعادة المكرم حفظه الله وفقه سلام عليكم ورحمة وبركاته
""".split())

# مرادفات بسيطة لتحسين البحث بالمعنى
SYNONYMS = {
    "اجازه": ["عطله", "غياب", "استئذان"],
    "عطله": ["اجازه", "اجازات"],
    "دوام": ["حضور", "انصراف", "ساعات"],
    "حضور": ["دوام", "غياب"],
    "تعميم": ["تعاميم", "اعمام"],
    "راتب": ["رواتب", "مرتب", "بدل", "مكافاه"],
    "مكافاه": ["راتب", "بدل", "حوافز"],
    "معلم": ["معلمين", "معلمه", "معلمات", "مدرس"],
    "طالب": ["طلاب", "طالبات", "طلبه"],
    "مدرسه": ["مدارس", "مدرسي"],
    "اختبار": ["اختبارات", "امتحان", "امتحانات"],
    "امتحان": ["اختبار", "اختبارات"],
    "تدريب": ["دوره", "دورات", "تطوير"],
    "ترقيه": ["ترقيات", "تثبيت"],
    "نقل": ["انتقال", "تكليف", "حركه"],
}


def normalize(text: str) -> str:
    """تطبيع النص العربي: إزالة التشكيل، توحيد الألف والياء والتاء المربوطة، والأرقام."""
    if not text:
        return ""
    t = text.translate(_AR_DIGITS)
    t = _TASHKEEL.sub("", t)
    t = re.sub("[إأآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = re.sub(r"[^\w\s/\-]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip().lower()


def stem(word: str) -> str:
    """تجذيع خفيف جداً: إزالة (ال) وبعض السوابق واللواحق الشائعة."""
    w = word
    for p in ("وال", "بال", "كال", "فال", "لل", "ال", "و"):
        if w.startswith(p) and len(w) - len(p) >= 3:
            w = w[len(p):]
            break
    for s in ("ات", "ون", "ين", "ان", "ه", "ها", "ي"):
        if w.endswith(s) and len(w) - len(s) >= 3:
            w = w[: -len(s)]
            break
    return w


def tokens(text: str):
    out = []
    for w in normalize(text).split():
        if len(w) < 2 or w in STOPWORDS:
            continue
        out.append(stem(w))
    return out


# ---------------------------------------------------------------------- OCR
def extract_text(path: str, ext: str) -> str:
    """يستخرج النص من PDF أو صورة. للـ PDF يجرّب النص المدمج أولاً ثم OCR."""
    ext = ext.lower().lstrip(".")
    try:
        if ext == "pdf":
            return _pdf_text(path)
        if ext in {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}:
            # Gemini أولاً (يفهم الصور)، وإن فشل أو لم يُفعَّل نستخدم Tesseract
            text = gemini_ocr(path, ext)
            if len(text) >= 20:
                return text
            return _image_ocr(path)
    except Exception:  # لا نكسر الرفع إذا فشل الـ OCR
        return ""
    return ""


def _image_ocr(path_or_img) -> str:
    import os
    import shutil
    import pytesseract
    from PIL import Image, ImageOps
    if not shutil.which("tesseract"):  # ويندوز: المسار الافتراضي إن لم يكن في PATH
        default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(default):
            pytesseract.pytesseract.tesseract_cmd = default
    img = path_or_img if hasattr(path_or_img, "convert") else Image.open(path_or_img)
    img = ImageOps.exif_transpose(img).convert("L")
    img = ImageOps.autocontrast(img)
    if img.width < 1400:  # تكبير الصور الصغيرة يحسّن دقة OCR
        ratio = 1400 / img.width
        img = img.resize((int(img.width * ratio), int(img.height * ratio)))
    return pytesseract.image_to_string(img, lang="ara+eng", config="--psm 6").strip()


_PRES_FORMS = re.compile("[ﭐ-﷿ﹰ-﻿]")


def _fix_visual_arabic(text: str) -> str:
    """بعض ملفات PDF تخزّن العربية بترتيب بصري معكوس وبأشكال العرض (ﻢﻴﻠﻌﺘﻟا).
    نحوّلها لحروف عادية ونعكس السطر ليصبح النص مقروءاً."""
    import unicodedata
    out = []
    for line in text.split("\n"):
        if _PRES_FORMS.search(line):
            # نعكس أولاً ثم نطبّع: حتى لا ينعكس ترتيب حروف اللام-ألف (ﻷ → لأ)
            line = unicodedata.normalize("NFKC", line[::-1]).replace("ـ", "")
            # الأرقام والكلمات اللاتينية انعكست مع السطر: نعيدها لوضعها الصحيح
            line = re.sub(r"[A-Za-z0-9][A-Za-z0-9.:/@_\-]*", lambda m: m.group(0)[::-1], line)
        # نص مزدوج (ظل): كل حرف مكرر مرتين → نختصره
        line = " ".join(
            w[::2] if len(w) >= 4 and len(w) % 2 == 0 and w[::2] == w[1::2] else w
            for w in line.split(" ")
        )
        out.append(line)
    return "\n".join(out)


def _pdf_text(path: str) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:30]:
            parts.append(_fix_visual_arabic(page.extract_text() or ""))
    text = "\n".join(parts).strip()
    if len(normalize(text)) >= 40:  # PDF نصّي
        return text
    # PDF ممسوح ضوئياً: Gemini يقرأ الملف مباشرة، وإلا نحوّل الصفحات لصور ثم Tesseract
    g = gemini_ocr(path, "pdf")
    if len(g) >= 20:
        return g
    from pdf2image import convert_from_path
    pages = convert_from_path(path, dpi=200, first_page=1, last_page=10)
    return "\n".join(_image_ocr(p) for p in pages).strip()


# ------------------------------------------------------------------- تلخيص
def summarize(text: str, max_sentences: int = 3) -> str:
    """تلخيص استخراجي: يختار أهم الجمل حسب تكرار الكلمات المفيدة."""
    if not text or len(text.strip()) < 80:
        return (text or "").strip()
    sentences = [s.strip() for s in re.split(r"[.،؛؟!?\n]+", text) if len(s.strip()) > 25]
    if len(sentences) <= max_sentences:
        return "، ".join(sentences)
    freq = Counter(t for s in sentences for t in tokens(s))
    scored = []
    for i, s in enumerate(sentences):
        toks = tokens(s)
        if not toks:
            continue
        score = sum(freq[t] for t in toks) / (len(toks) ** 0.6)
        if i < 3:  # الجمل الأولى غالباً تحمل الموضوع
            score *= 1.3
        scored.append((score, i, s))
    top = sorted(sorted(scored, reverse=True)[:max_sentences], key=lambda x: x[1])
    return "، ".join(s for _, _, s in top)


# ------------------------------------------------------------ تصنيف تلقائي
CATEGORY_KEYWORDS = {
    "تعميم": ["تعميم", "نفيدكم", "نود الاشعار", "نود الإشعار", "للعلم والتقيد", "يعمم"],
    "قرار": ["قرار", "يقرر", "تقرر", "قررنا", "يعتمد", "اعتماد"],
    "محضر": ["محضر", "اجتماع", "حضر", "المجتمعون", "جلسه", "جلسة"],
    "نموذج": ["نموذج", "استمارة", "طلب", "تعبئة"],
    "لائحة / تعليمات": ["لائحه", "لائحة", "تعليمات", "دليل", "ضوابط", "نظام", "اجراءات", "إجراءات"],
    "خطاب": ["خطاب", "سعادة", "المكرم", "سلمه الله", "حفظه الله", "تحيه طيبه", "تحية طيبة", "بالاشاره", "بالإشارة"],
}


def classify(text: str, categories: list[str]) -> str | None:
    """يقترح تصنيف الوثيقة بحسب الكلمات المفتاحية (الأسطر الأولى أثقل وزناً)."""
    if not text:
        return None
    head = normalize(text[:400])
    body = normalize(text)
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        if cat not in categories:
            continue
        s = 0
        for kw in kws:
            k = normalize(kw)
            s += 3 * head.count(k) + body.count(k)
        if s:
            scores[cat] = s
    return max(scores, key=scores.get) if scores else None


# -------------------------------------------------------- استخراج الحقول
_NUM_RE = re.compile(r"(?:الرقم|رقم)\s*[:：]?\s*([0-9]{2,}[0-9/\-]*)")
_DATE_RES = [
    re.compile(r"(\d{1,2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*(?:13|14|19|20)\d{2})\s*(?:هـ|ه|م)?"),
    re.compile(r"((?:13|14|19|20)\d{2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{1,2})\s*(?:هـ|ه|م)?"),
]


def extract_fields(text: str) -> dict:
    """يحاول استخراج رقم الوثيقة وتاريخها وعنوانها من النص."""
    t = (text or "").translate(_AR_DIGITS)
    out = {"doc_number": None, "doc_date": None, "title": None, "source": None}
    m = re.search(r"(?:الجهة(?:\s+المصدرة)?|المرسل|صادر\s+من)\s*[:：]\s*(.{4,80})", t)
    if m:
        out["source"] = m.group(1).split("\n")[0].strip(" :-")
    else:  # الجهة غالباً في ترويسة الوثيقة (أول أسطرها)
        for line in t.splitlines()[:12]:
            line = line.strip()
            if 6 <= len(line) <= 70 and re.match(r"(?:وزارة|الإدارة|إدارة|مكتب|هيئة|الهيئة|جامعة|مدرسة|المديرية)", line):
                out["source"] = line
                break
    m = _NUM_RE.search(t)
    if m:
        out["doc_number"] = m.group(1).strip("-/")
    for rx in _DATE_RES:
        m = rx.search(t)
        if m:
            out["doc_date"] = re.sub(r"\s+", "", m.group(1))
            break
    m = re.search(r"(?:الموضوع|بشأن|بخصوص)\s*[:：]?\s*(.{8,120})", t)
    if m:
        out["title"] = m.group(1).split("\n")[0].strip(" :-")
    else:
        for line in t.splitlines():
            if len(line.strip()) >= 12 and len(tokens(line)) >= 2:
                out["title"] = line.strip()[:120]
                break
    return out


# ------------------------------------------------------- Gemini (اختياري)
def gemini_enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def gemini_analyze(text: str, categories: list[str]) -> dict | None:
    """يحلل الوثيقة بـ Gemini ويرجع {title, doc_number, doc_date, category, summary}.
    يرجع None عند أي فشل (لا مفتاح، لا إنترنت، تجاوز الحد...) ليعمل البديل المحلي."""
    if not gemini_enabled() or not text or len(text.strip()) < 20:
        return None
    prompt = (
        "أنت مساعد أرشفة لوثائق إدارية عربية (تعاميم، قرارات، خطابات). "
        "حلّل نص الوثيقة التالي (قد يحتوي أخطاء OCR بسيطة) وأرجع JSON فقط بالحقول:\n"
        "title: عنوان مختصر للموضوع (أقل من 120 حرفاً)\n"
        "doc_number: رقم الوثيقة أو null\n"
        "doc_date: التاريخ كما ورد (هجري أو ميلادي) أو null\n"
        "source: الجهة المصدرة للوثيقة (الإدارة أو الوزارة أو المدرسة التي أصدرتها، من الترويسة أو التوقيع) أو null\n"
        f"category: واحد بالضبط من {json.dumps(categories, ensure_ascii=False)} أو null\n"
        "summary: ملخص بالعربية من 2 إلى 3 جمل يوضح المطلوب والجهة والمواعيد.\n"
        "لا تخترع معلومات غير موجودة في النص.\n\nنص الوثيقة:\n" + text[:12000]
    )
    try:
        res = json.loads(_gemini_call([{"text": prompt}], json_mode=True))
        if not isinstance(res, dict):
            return None
        return {k: (str(res[k]).strip() if res.get(k) else None)
                for k in ("title", "doc_number", "doc_date", "source", "category", "summary")}
    except Exception:
        return None


def _gemini_call(parts: list, json_mode: bool = False, timeout: int = 90) -> str:
    """يرسل طلباً إلى Gemini ويرجع النص الناتج. يعيد المحاولة عند الازدحام المؤقت."""
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    cfg = {"temperature": 0.0}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    body = json.dumps({"contents": [{"parts": parts}], "generationConfig": cfg}).encode("utf-8")
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": os.getenv("GEMINI_API_KEY", "")})
    data = None
    for attempt in range(3):  # 503/429 مؤقتة غالباً: نعيد المحاولة
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 503) or attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return data["candidates"][0]["content"]["parts"][0]["text"]


_MIME = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "webp": "image/webp", "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff"}


def gemini_ocr(path: str, ext: str) -> str:
    """يقرأ صورة أو PDF ممسوح مباشرة بـ Gemini (رؤية حاسوبية) ويرجع النص الكامل.
    أدق من Tesseract مع الصور الضعيفة والخطوط المتنوعة والأختام. يرجع "" عند الفشل."""
    import base64
    mime = _MIME.get(ext.lower().lstrip("."))
    if not gemini_enabled() or not mime or os.path.getsize(path) > 15 * 1024 * 1024:
        return ""
    prompt = (
        "انسخ كل النص الموجود في هذه الوثيقة العربية كما هو مكتوب، بنفس ترتيب القراءة "
        "(من الأعلى للأسفل ومن اليمين لليسار)، بدون تلخيص أو شرح أو تصحيح للمعنى. "
        "حافظ على الأرقام والتواريخ ورقم الوثيقة بدقة، وانسخ الجداول سطراً بسطر. "
        "إذا وُجد ختم أو توقيع اكتب [ختم] أو [توقيع]. أرجع النص فقط.")
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    try:
        return _gemini_call(
            [{"inline_data": {"mime_type": mime, "data": b64}}, {"text": prompt}],
            timeout=120).strip()
    except Exception:
        return ""


# ------------------------------------------------------------- بحث ذكي
def expand_query(q: str) -> list[str]:
    toks = tokens(q)
    expanded = list(toks)
    for t in toks:
        for key, syns in SYNONYMS.items():
            if t == stem(key) or t == key:
                expanded += [stem(s) for s in syns]
    return expanded


def rank(query: str, docs: list[dict]) -> list[dict]:
    """يرتب الوثائق بحسب التطابق مع الاستعلام (العنوان أعلى وزناً من النص).
    الكلمات الأصلية وزنها كامل، والمرادفات وزنها أقل."""
    base = tokens(query)
    if not base:
        return docs
    syn_only = [t for t in expand_query(query) if t not in base]
    results = []
    for d in docs:
        title_t = tokens(d.get("title") or "")
        body_t = (d.get("search_text") or "").split()
        meta_t = tokens(f"{d.get('doc_number') or ''} {d.get('source') or ''} {d.get('description') or ''}")
        body_counts = Counter(body_t)
        score = 0.0
        for t in base:
            score += 5 * title_t.count(t) + 2 * meta_t.count(t) + min(body_counts.get(t, 0), 5)
        for t in syn_only:
            score += 0.8 * title_t.count(t) + 0.3 * min(body_counts.get(t, 0), 5)
        if score > 0:
            results.append((score, d))
    results.sort(key=lambda x: -x[0])
    return [dict(d, _score=round(s, 1)) for s, d in results]


def build_search_text(*parts: str) -> str:
    return " ".join(tokens(" ".join(p for p in parts if p)))
