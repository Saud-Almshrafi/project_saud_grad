"""أدوات التاريخ الهجري (تقويم أم القرى عبر hijri-converter، بلا إنترنت).

التخزين: doc_date_h نص منتظم 'YYYY-MM-DD' هجرياً (مثل 1447-05-12) فيُرتَّب ويُقارن نصياً صحيحاً.
حدود المكتبة: 1343-1500 هـ (تقريباً 1924-2077 م)؛ ما خارجها لا يمكن التحقق منه فيُعامل كغير صالح.
"""
import re
import warnings
from datetime import datetime, timedelta, timezone
from functools import lru_cache

with warnings.catch_warnings():  # المكتبة تطبع تنبيه "deprecated" عند الاستيراد
    warnings.simplefilter("ignore", DeprecationWarning)
    from hijri_converter import Gregorian, Hijri

MONTHS = ["محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة",
          "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذو الحجة"]
MIN_YEAR = 1400  # أقل سنة في قوائم الاختيار
HIJRI_RANGE = (1300, 1500)
GREG_RANGE = (1900, 2100)
# توقيت الرياض ثابت UTC+3 (لا توقيت صيفي). نتجنب zoneinfo لأنها تحتاج حزمة tzdata على ويندوز.
RIYADH = timezone(timedelta(hours=3), "Asia/Riyadh")

ERR_INCOMPLETE = "اختر السنة والشهر واليوم كاملة، أو اترك التاريخ فارغاً."
ERR_PARTIAL = "اختر السنة أولاً، ثم الشهر، ثم اليوم (يمكن الاكتفاء بالسنة أو بالسنة والشهر)."
ERR_INVALID ="التاريخ المختار غير صالح (تحقق من عدد أيام الشهر)."
ERR_FUTURE = "لا يمكن اختيار تاريخ بعد تاريخ اليوم الهجري."
ERR_RANGE = f"السنة يجب أن تكون بين {MIN_YEAR} والسنة الهجرية الحالية."

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SEP = r"\s*[/\-.]\s*"
_Y_FIRST = re.compile(rf"(\d{{4}}){_SEP}(\d{{1,2}}){_SEP}(\d{{1,2}})")
_Y_LAST = re.compile(rf"(\d{{1,2}}){_SEP}(\d{{1,2}}){_SEP}(\d{{4}})")
_HIJRI_MARK = re.compile(r"\s*(?:هـ|ه|هجري|هجرية)\.?\s*$")
_GREG_MARK = re.compile(r"\s*(?:م|ميلادي|ميلادية)\.?\s*$")
_ISO_H = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def to_iso(y: int, m: int, d: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"


def is_valid_hijri(y: int, m: int, d: int) -> bool:
    """يتحقق من الشهر ومن عدد أيامه الفعلي في تقويم أم القرى."""
    try:
        Hijri(int(y), int(m), int(d))
        return True
    except (ValueError, OverflowError, TypeError):
        return False


@lru_cache(maxsize=None)
def month_length(y: int, m: int) -> int | None:
    try:
        return Hijri(int(y), int(m), 1).month_length()
    except (ValueError, OverflowError, TypeError):
        return None


def today_hijri() -> str:
    """تاريخ اليوم الهجري بتوقيت الرياض، بصيغة YYYY-MM-DD."""
    h = Gregorian.fromdate(datetime.now(RIYADH).date()).to_hijri()
    return to_iso(h.year, h.month, h.day)


def split_iso(s: str | None):
    """'1447-05-12' → (1447, 5, 12) إن كانت صيغة منتظمة وتاريخاً صالحاً، وإلا None."""
    m = _ISO_H.fullmatch((s or "").strip())
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return (y, mo, d) if is_valid_hijri(y, mo, d) else None


def _norm_ar(s: str) -> str:
    """توحيد بسيط لأسماء الأشهر: الهمزات، ى/ي، ة/ه، التطويل، المسافات."""
    s = re.sub("[إأآ]", "ا", s).replace("ى", "ي").replace("ة", "ه").replace("ـ", "")
    return re.sub(r"\s+", " ", s).strip()


# أسماء الأشهر الهجرية وصيغها الشائعة (بعد التوحيد) → رقم الشهر. «جمادى» وحدها غامضة فلا تُقبل.
_MONTH_ALIASES = {
    1: ["محرم"], 2: ["صفر"],
    3: ["ربيع الاول", "ربيع اول"], 4: ["ربيع الاخر", "ربيع الثاني", "ربيع ثاني", "ربيع اخر"],
    5: ["جمادي الاولي", "جمادي الاول", "جماد الاول"], 6: ["جمادي الاخره", "جمادي الثانيه", "جمادي الاخر", "جمادي الثاني", "جماد الثاني"],
    7: ["رجب"], 8: ["شعبان"], 9: ["رمضان"], 10: ["شوال"],
    11: ["ذو القعده", "ذي القعده"], 12: ["ذو الحجه", "ذي الحجه"],
}
MONTH_BY_NAME = {alias: m for m, names in _MONTH_ALIASES.items() for alias in names}
_MONTH_ALT = "|".join(sorted(map(re.escape, MONTH_BY_NAME), key=len, reverse=True))
# مثل: «12 ربيع الأول 1447»، «12 من شهر رمضان لعام 1446هـ»
NAMED_DATE = re.compile(rf"(\d{{1,2}})\s+(?:من\s+)?(?:شهر\s+)?({_MONTH_ALT})\s+(?:(?:لعام|عام|سنه|لسنه)\s+)?(\d{{4}})")


def parse_any_date_kind(text: str | None):
    """مثل parse_any_date لكن يرجع أيضاً نوع المصدر: ('1447-05-12', 'h') أو (..., 'g') أو None."""
    t = (text or "").translate(_DIGITS).replace("‏", "").replace("‎", "").strip()
    if not t:
        return None
    marked_h = bool(_HIJRI_MARK.search(t))
    marked_g = bool(_GREG_MARK.search(t))
    t = _GREG_MARK.sub("", _HIJRI_MARK.sub("", t))
    named = NAMED_DATE.fullmatch(_norm_ar(t))
    if named:  # الشهر مكتوب باسمه → هجري حتماً
        y, mo, d = int(named[3]), MONTH_BY_NAME[named[2]], int(named[1])
        if marked_g or not (HIJRI_RANGE[0] <= y <= HIJRI_RANGE[1]) or not is_valid_hijri(y, mo, d):
            return None
        return to_iso(y, mo, d), "h"
    m = _Y_FIRST.fullmatch(t)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = _Y_LAST.fullmatch(t)
        if not m:
            return None
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    if HIJRI_RANGE[0] <= y <= HIJRI_RANGE[1]:
        if marked_g or not is_valid_hijri(y, mo, d):
            return None
        return to_iso(y, mo, d), "h"
    if GREG_RANGE[0] <= y <= GREG_RANGE[1]:
        if marked_h:
            return None
        try:
            h = Gregorian(y, mo, d).to_hijri()
        except (ValueError, OverflowError):
            return None
        return to_iso(h.year, h.month, h.day), "g"
    return None


def parse_any_date(text: str | None) -> str | None:
    """يحوّل نص تاريخ (هجري أو ميلادي) إلى هجري 'YYYY-MM-DD'، أو None إن كان غامضاً أو غير صالح.

    يقبل الأرقام العربية والهندية والفواصل / و - و . وصيغتي YYYY/MM/DD و DD/MM/YYYY.
    النوع يُحدَّد بالسنة: 1300-1500 هجري، 1900-2100 ميلادي (ويُحوَّل إلى هجري)."""
    r = parse_any_date_kind(text)
    return r[0] if r else None


def format_hijri(s: str | None) -> str:
    """'1447-05-12' → '12 جمادى الأولى 1447هـ'، وفارغ إن لم يكن تاريخاً صالحاً."""
    p = split_iso(s)
    if not p:
        return ""
    y, m, d = p
    return f"{d} {MONTHS[m - 1]} {y}هـ"


def _int_or_none(v):
    v = (v or "").strip() if isinstance(v, str) else v
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError


def from_picker(y, m, d, today: str | None = None):
    """تاريخ كامل من قوائم الاختيار (الرفع/التعديل). يرجع (iso, None) أو (None, None) إن كان فارغاً
    أو (None, رسالة_خطأ)."""
    today = today or today_hijri()
    try:
        y, m, d = _int_or_none(y), _int_or_none(m), _int_or_none(d)
    except ValueError:
        return None, ERR_INVALID
    if y is None and m is None and d is None:
        return None, None
    if None in (y, m, d):
        return None, ERR_INCOMPLETE
    if not (MIN_YEAR <= y <= int(today[:4])):
        return None, ERR_RANGE
    if not is_valid_hijri(y, m, d):
        return None, ERR_INVALID
    iso = to_iso(y, m, d)
    if iso > today:
        return None, ERR_FUTURE
    return iso, None


def range_bound(y, m, d, end: bool, today: str | None = None):
    """حد بحث من قوائم جزئية: سنة فقط، أو سنة+شهر، أو تاريخ كامل.
    'من' (end=False) يأخذ أول الفترة، و'إلى' (end=True) آخرها. يرجع (iso, None) أو (None, None) أو (None, خطأ).
    الفترة التي يبدأ أولها بعد اليوم مرفوضة؛ وإن انتهت بعد اليوم (مثل 'إلى سنة الحالية') تُقصّ عند اليوم."""
    today = today or today_hijri()
    try:
        y, m, d = _int_or_none(y), _int_or_none(m), _int_or_none(d)
    except ValueError:
        return None, ERR_INVALID
    if y is None and m is None and d is None:
        return None, None
    if y is None or (m is None and d is not None):
        return None, ERR_PARTIAL
    if not (MIN_YEAR <= y <= int(today[:4])):
        return None, ERR_RANGE
    if m is not None and not 1 <= m <= 12:
        return None, ERR_INVALID
    if d is not None:
        if not is_valid_hijri(y, m, d):
            return None, ERR_INVALID
        first = last = to_iso(y, m, d)
    elif m is not None:
        n = month_length(y, m)
        if not n:
            return None, ERR_INVALID
        first, last = to_iso(y, m, 1), to_iso(y, m, n)
    else:
        n = month_length(y, 12)
        if not n:
            return None, ERR_INVALID
        first, last = to_iso(y, 1, 1), to_iso(y, 12, n)
    if first > today:
        return None, ERR_FUTURE
    return (min(last, today) if end else first), None


_PARTS = re.compile(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?")


def split_parts(value: str | None):
    """قيمة الحقل المخفي ('1447-05-12'، أو جزئية '1447' / '1447-05' في روابط البحث) → (y, m, d) كنصوص
    ('' للمفقود). فارغ → ('', '', ''). صيغة غير مفهومة → None."""
    v = (value or "").strip()
    if not v:
        return "", "", ""
    m = _PARTS.fullmatch(v)
    return (m[1], m[2] or "", m[3] or "") if m else None


@lru_cache(maxsize=None)
def _first_weekday(y: int, m: int) -> int:
    """يوم الأسبوع لأول يوم في الشهر الهجري: 0=الأحد ... 6=السبت."""
    return (Hijri(y, m, 1).to_gregorian().weekday() + 1) % 7  # weekday(): الاثنين=0


def calendar_data(today: str | None = None) -> dict:
    """جدول التقويم الذي يقرؤه المكوّن في المتصفح (لا منطق تقويم في JS):
    لكل سنة من 1400 حتى الحالية: [[عدد أيام الشهر, يوم الأسبوع لأوله (0=الأحد)], ...12]."""
    today = today or today_hijri()
    ty = int(today[:4])
    return {"min": MIN_YEAR, "today": today, "months": MONTHS,
            "years": {str(y): [[month_length(y, m), _first_weekday(y, m)] for m in range(1, 13)]
                      for y in range(MIN_YEAR, ty + 1)}}


def _as_utc(value):
    """قيمة وقت من القاعدة (datetime أو نص 'YYYY-MM-DD HH:MM:SS') مخزّنة بتوقيت UTC → datetime مدرك للتوقيت."""
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("T", " ")[:19])
        except ValueError:
            return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def format_riyadh(value) -> str:
    """وقت UTC → '12 جمادى الأولى 1447هـ — 10:32 م' بتوقيت الرياض، وفارغ إن لم يوجد."""
    dt = _as_utc(value)
    if not dt:
        return ""
    local = dt.astimezone(RIYADH)
    h = Gregorian.fromdate(local.date()).to_hijri()
    hour = local.hour % 12 or 12
    return f"{format_hijri(to_iso(h.year, h.month, h.day))} — {hour}:{local.minute:02d} {'ص' if local.hour < 12 else 'م'}"


def hijri_to_gregorian(iso: str | None):
    """'1446-09-12' → date(2025, 3, 12) عبر hijri-converter، أو None إن لم يكن تاريخاً صالحاً."""
    p = split_iso(iso)
    if not p:
        return None
    g = Hijri(*p).to_gregorian()
    return datetime(g.year, g.month, g.day).date()


def upload_bounds_utc(h_from: str | None, h_to: str | None):
    """حدود البحث بتاريخ الرفع: يوما «من/إلى» الهجريان بتوقيت الرياض → نطاق UTC للمقارنة مع created_at.
    يرجع (start, end) نصوصاً 'YYYY-MM-DD HH:MM:SS' بتوقيت UTC، حيث: created_at >= start و created_at < end
    (end = بداية اليوم التالي لـ«إلى»، فيشمل آخر ثانية منه). أي طرف غائب → None."""
    def riyadh_midnight_utc(g, plus_days=0):
        local = datetime(g.year, g.month, g.day, tzinfo=RIYADH) + timedelta(days=plus_days)
        return local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    gf, gt = hijri_to_gregorian(h_from), hijri_to_gregorian(h_to)
    return (riyadh_midnight_utc(gf) if gf else None, riyadh_midnight_utc(gt, 1) if gt else None)


def riyadh_hijri_date(value) -> str:
    """وقت UTC من القاعدة → التاريخ الهجري لليوم المقابل بتوقيت الرياض ('YYYY-MM-DD')، أو فارغ."""
    dt = _as_utc(value)
    if not dt:
        return ""
    h = Gregorian.fromdate(dt.astimezone(RIYADH).date()).to_hijri()
    return to_iso(h.year, h.month, h.day)


def utc_now_str() -> str:
    """الوقت الحالي UTC بصيغة 'YYYY-MM-DD HH:MM:SS' للتخزين في DATETIME (متّسق مع created_at)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
