"""تحليل التواريخ الميلادية للبحث بالنطاق (doc_date_greg).

العمود النصي doc_date يبقى كما هو مكتوب في الوثيقة (هجري أو ميلادي).
هنا فقط نستخرج التاريخ الميلادي الواضح، ولا نخمّن في الهجري ولا في الصيغ الغامضة.
"""
import re
from datetime import date

MIN_YEAR = 1900
ERR_FORMAT = "صيغة التاريخ غير صالحة، اختر التاريخ من المنتقي."
ERR_FUTURE = "لا يمكن أن يكون التاريخ في المستقبل."

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_Y_M_D = re.compile(r"(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})")
_D_M_Y = re.compile(r"(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})")
_GREG_SUFFIX = re.compile(r"\s*(?:ميلادي|ميلادية|م)\s*$")


def _build(y: int, m: int, d: int, today: date) -> str | None:
    try:
        dt = date(y, m, d)
    except ValueError:
        return None
    if dt.year < MIN_YEAR or dt > today:
        return None
    return dt.isoformat()


def parse_form_date(value: str | None, today: date | None = None):
    """يتحقق من قيمة منتقي التاريخ (YYYY-MM-DD).
    يرجع (iso, None) أو (None, None) إن كانت فارغة، أو (None, رسالة_خطأ)."""
    today = today or date.today()
    v = (value or "").strip()
    if not v:
        return None, None
    if not _ISO.fullmatch(v):
        return None, ERR_FORMAT
    try:
        dt = date.fromisoformat(v)
    except ValueError:
        return None, ERR_FORMAT
    if dt.year < MIN_YEAR:
        return None, ERR_FORMAT
    if dt > today:
        return None, ERR_FUTURE
    return dt.isoformat(), None


def clear_gregorian(text: str | None, today: date | None = None) -> str | None:
    """يرجع 'YYYY-MM-DD' فقط إذا كان النص تاريخاً ميلادياً واضحاً، وإلا None.

    المقبول: YYYY-MM-DD أو YYYY/MM/DD أو DD/MM/YYYY (يُقبل - بدل /، وأرقام عربية،
    وملحق «م» أو «ميلادي»). السنة بين 1900 واليوم. أي نص فيه «هـ» أو سنة هجرية يُترك."""
    today = today or date.today()
    t = (text or "").translate(_AR_DIGITS).replace("‏", "").replace("‎", "").strip()
    if not t:
        return None
    t = _GREG_SUFFIX.sub("", t)
    m = _Y_M_D.fullmatch(t)
    if m:
        return _build(int(m[1]), int(m[2]), int(m[3]), today)
    m = _D_M_Y.fullmatch(t)
    if m:
        return _build(int(m[3]), int(m[2]), int(m[1]), today)
    return None
