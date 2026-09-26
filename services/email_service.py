import os
import threading
import logging
from datetime import datetime
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


def send_admin_alert_async(student_name: str, phone_number: str, total_students_count: int):
    """Sends an instant email alert to the admin in a background thread and logs locally."""
    def _send():
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{now_str}] 📌 تسجيل مستخدم جديد | الاسم: {student_name} | رقم الهاتف: {phone_number} | إجمالي المسجلين: {total_students_count}\n"
        
        # 1. Local persistent logging guaranteed
        try:
            log_path = os.path.join(settings.BASE_DIR, 'admin_registrations.log')
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            logger.error(f"[REGISTRATION LOG ERROR] {e}")

        try:
            print(f"\n==========================================")
            print(f"[NEW USER REGISTERED]")
            print(f"Name: {student_name}")
            print(f"Phone: {phone_number}")
            print(f"Total Registrations: {total_students_count}")
            print(f"Time: {now_str}")
            print(f"==========================================\n")
        except Exception:
            pass

        # 2. Email Notification to Admin
        subject = f"تسجيل مستخدم جديد: {student_name} ({phone_number})"
        body = f"""تحية طيبة مهندس عبدالرحمن،

تم تسجيل مستخدم جديد بنجاح في بوابة علامات ونتائج كلية الهندسة المعلوماتية - جامعة دمشق:

• الاسم الكامل للمسجل: {student_name}
• رقم الهاتف: {phone_number}
• إجمالي عدد الطلاب والمستخدمين المسجلين: {total_students_count}
• تاريخ ووقت التسجيل: {now_str}

---
بوابة كلية الهندسة المعلوماتية - جامعة دمشق
تم الإرسال آلياً إلى: eng.abdulrahman.saleh2003@gmail.com
"""
        admin_email = getattr(settings, 'ADMIN_EMAIL', 'eng.abdulrahman.saleh2003@gmail.com')
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', admin_email)
        
        try:
            sent = send_mail(
                subject=subject,
                message=body,
                from_email=from_email,
                recipient_list=[admin_email],
                fail_silently=False
            )
            print(f"[EMAIL SERVICE] Admin alert dispatched to {admin_email} (sent: {sent})")
        except Exception as e:
            print(f"[EMAIL SERVICE NOTICE] SMTP dispatch to {admin_email} encountered: {e}")
            print(f"[EMAIL SERVICE NOTICE] (Registration was successfully saved in database and admin_registrations.log)")

    threading.Thread(target=_send, daemon=True).start()


def send_otp_email_async(to_email: str, otp_code: str, student_name: str):
    """Sends password reset OTP email in a background thread."""
    def _send():
        subject = "🔑 رمز استعادة كلمة المرور - كلية الهندسة المعلوماتية"
        body = f"""مرحباً {student_name}،

لقد طلبت إعادة تعيين كلمة المرور لحسابك في تطبيق علامات كلية الهندسة المعلوماتية.
رمز التحقق الخاص بك هو:

===================
      {otp_code}
===================

هذا الرمز صالح لمدة 10 دقائق فقط. إذا لم تكن أنت من طلب ذلك، يرجى تجاهل هذه الرسالة.

كلية الهندسة المعلوماتية - جامعة دمشق
"""
        admin_email = getattr(settings, 'ADMIN_EMAIL', 'eng.abdulrahman.saleh2003@gmail.com')
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', admin_email)
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=from_email,
                recipient_list=[to_email],
                fail_silently=True
            )
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()

