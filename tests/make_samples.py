"""يولّد وثائق عربية تجريبية (صور) لاختبار OCR والبحث."""
import os
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
OUT = os.path.join(os.path.dirname(__file__), "samples")

DOCS = {
 "circular_leave.png": [
  "تعميم", "الرقم: 4712345", "التاريخ: 1447/05/12 هـ",
  "الموضوع: ضوابط الإجازات الاعتيادية للمعلمين والمعلمات",
  "نفيدكم بأنه تقرر اعتماد الضوابط الجديدة للإجازات الاعتيادية للمعلمين",
  "على أن يتم تقديم الطلب قبل بداية الإجازة بمدة لا تقل عن أسبوعين",
  "للعلم والتقيد بما ورد في هذا التعميم وإبلاغ جميع منسوبي المدارس",
 ],
 "decision_exams.png": [
  "قرار", "رقم: 5598821", "التاريخ: 1447/06/03 هـ",
  "الموضوع: اعتماد جدول الاختبارات النهائية للفصل الدراسي الأول",
  "يقرر مدير الإدارة اعتماد جدول الاختبارات النهائية للطلاب والطالبات",
  "ويبدأ تطبيق الجدول من بداية الأسبوع القادم في جميع المدارس",
 ],
}
for name, lines in DOCS.items():
    img = Image.new("RGB", (1400, 220 + 110 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 44)
    y = 60
    for line in lines:
        d.text((1340, y), line, font=f, fill="black", anchor="ra", direction="rtl", language="ar")
        y += 110
    img.save(os.path.join(OUT, name))
print("samples ready")
