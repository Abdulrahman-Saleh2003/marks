# marks - ITE Damascus University Marks Portal (Backend) 🎓

نظام إدارة وعرض علامات طلاب كلية الهندسة المعلوماتية - جامعة دمشق (الواجهة الخلفية / Backend).

## 🚀 المميزات التقنية (Features)
- **Django 5 & Django REST Framework:** واجهة برمجية سريعة ومحمية لإدارة نتائج المواد والطلاب.
- **JWT & Custom Authentication:** نظام توثيق للمستخدمين والطلاب برقم الهاتف وكلمة المرور.
- **إشعارات فورية (Instant Alerts):**
  - تنبيهات فورية عبر **Telegram Bot** عند تسجيل أي طالب جديد.
  - إشعارات بريد إلكتروني تلقائية للمشرف عبر **Gmail SMTP**.
- **معدل الطلبات والحماية (Throttling & Security):**
  - تقييد معدل الطلبات (Rate Limiting) لحماية المنظومة من هجمات الإغراق والتخمين.
  - ترويسات أمان قياسية (XSS Protection, Content Type No Sniff, Clickjacking Protection).
- **جاهزية النشر السحابي (Cloud Production Ready):**
  - خادم إنتاج **Gunicorn** متعدد الخيوط مع ملف Procfile.
  - معالجة وتخديم الملفات الثابتة عبر **WhiteNoise**.
  - دعم قواعد بيانات سحابية (PostgreSQL) عبر DATABASE_URL مع التوافق مع SQLite محلياً.

---

## 🛠️ متطلبات التثبيت والتشغيل المحلي (Local Setup)

1. إنشاء وتفعيل بيئة العمل الافتراضية:
   \\ash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   \
2. تثبيت الحزم المطلوبة:
   \\ash
   pip install -r requirements.txt
   \
3. ضبط المتغيرات البيئية:
   قم بنسخ ملف \.env.example\ إلى \.env\ واملأ القيم الخاصة بك:
   \\ash
   cp .env.example .env
   \
4. تطبيق الهجرات وتشغيل الخادم:
   \\ash
   python manage.py migrate
   python manage.py runserver
   \
---

## ☁️ النشر على المنصات السحابية (Deployment)

المشروع مهيأ للنشر الفوري على منصات مثل **Render** أو **Railway**:
- **Build Command:**
  \\ash
  pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --noinput
  \- **Start Command:**
  \\ash
  gunicorn project.wsgi:application
  \
