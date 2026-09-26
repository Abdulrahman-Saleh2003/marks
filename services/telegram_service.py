import os
import threading
import urllib.request
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def send_telegram_alert_async(student_name: str, phone_number: str, total_students_count: int):
    """Sends an instant notification to admin via Telegram Bot in a background thread."""
    def _send():
        bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', os.getenv('TELEGRAM_BOT_TOKEN', ''))
        chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', os.getenv('TELEGRAM_CHAT_ID', ''))

        if not bot_token or not chat_id:
            return

        text = (
            f"🔔 <b>تسجيل مستخدم جديد في المنظومة</b>\n\n"
            f"👤 <b>الاسم الكامل:</b> {student_name}\n"
            f"📱 <b>رقم الهاتف:</b> <code>{phone_number}</code>\n"
            f"📊 <b>إجمالي المسجلين:</b> {total_students_count} طالب\n"
            f"⏰ <b>التوقيت:</b> للتو\n\n"
            f"🏛 <i>بوابة كلية الهندسة المعلوماتية - جامعة دمشق</i>"
        )

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[TELEGRAM SERVICE] Alert sent to Telegram chat {chat_id}, status: {resp.status}")
        except Exception as e:
            print(f"[TELEGRAM SERVICE NOTICE] Telegram dispatch encountered: {e}")

    threading.Thread(target=_send, daemon=True).start()
