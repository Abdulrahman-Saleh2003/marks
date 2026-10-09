import os
import threading
import urllib.request
import json
import logging
import time
from django.conf import settings

logger = logging.getLogger(__name__)

# In-memory dictionary to track chat states for conversational flows
# Key: chat_id -> Value: {'state': str, 'timestamp': float}
USER_CONVERSATIONS = {}

ADMIN_SECRET_PASSWORD = "2004"


def get_bot_credentials():
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', os.getenv('TELEGRAM_BOT_TOKEN', ''))
    default_chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', os.getenv('TELEGRAM_CHAT_ID', ''))
    return bot_token, default_chat_id


def send_telegram_message(chat_id, text, reply_markup=None):
    """Sends a message to a specific chat_id via Telegram Bot API."""
    bot_token, _ = get_bot_credentials()
    if not bot_token or not chat_id:
        logger.warning("[TELEGRAM] Missing bot_token or chat_id for sendMessage.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"[TELEGRAM ERROR] Failed to send message to {chat_id}: {e}")
        return False


def send_telegram_alert_async(student_name: str, phone_number: str, total_students_count: int):
    """Sends an instant notification to admin via Telegram Bot in a background thread."""
    def _send():
        bot_token, chat_id = get_bot_credentials()
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
        send_telegram_message(chat_id, text)

    threading.Thread(target=_send, daemon=True).start()


def get_main_keyboard():
    """Returns the default reply keyboard for the admin bot."""
    return {
        "keyboard": [
            [{"text": "👥 اريد المستخدمين"}, {"text": "📊 احصائيات المنظومة"}],
            [{"text": "❓ مساعدة"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


def handle_telegram_update(update_data: dict):
    """
    Core message processor for incoming Telegram updates.
    Handles user commands, authentication with secret code 2004, and listing users.
    """
    message = update_data.get('message') or update_data.get('channel_post') or {}
    if not message:
        return

    chat = message.get('chat', {})
    chat_id = chat.get('id')
    raw_text = (message.get('text') or '').strip()

    if not chat_id or not raw_text:
        return

    normalized_text = raw_text.strip().lower()

    # Expire old conversation states (> 10 minutes)
    current_time = time.time()
    chat_state_info = USER_CONVERSATIONS.get(chat_id)
    if chat_state_info and (current_time - chat_state_info.get('timestamp', 0) > 600):
        USER_CONVERSATIONS.pop(chat_id, None)
        chat_state_info = None

    # Check if this chat is awaiting password
    if chat_state_info and chat_state_info.get('state') == 'AWAITING_USERS_PASSWORD':
        if raw_text == ADMIN_SECRET_PASSWORD:
            USER_CONVERSATIONS.pop(chat_id, None)
            _send_users_list(chat_id)
        else:
            USER_CONVERSATIONS.pop(chat_id, None)
            error_msg = (
                "❌ <b>كلمة السر غير صحيحة!</b>\n\n"
                "تم رفض الوصول إلى قائمة المستخدمين وأرقام الهواتف لأسباب أمنية.\n\n"
                "💡 للمحاولة مجدداً، أرسل: <b>اريد المستخدمين</b>"
            )
            send_telegram_message(chat_id, error_msg, reply_markup=get_main_keyboard())
        return

    # 1. User wants to see registered users
    trigger_words = [
        'اريد المستخدمين',
        'أريد المستخدمين',
        'اريد المستخدمين المسجلين',
        'أريد المستخدمين المسجلين',
        'المستخدمين',
        'المستخدمين المسجلين',
        '/users',
        'users',
        '👥 اريد المستخدمين'
    ]

    if any(trigger in raw_text for trigger in trigger_words) or normalized_text in ['/users', 'users']:
        USER_CONVERSATIONS[chat_id] = {
            'state': 'AWAITING_USERS_PASSWORD',
            'timestamp': current_time
        }
        prompt_msg = (
            "🔒 <b>مطلوب التحقق الأمني من هوية المشرف</b>\n\n"
            "الرجاء إدخال كلمة السر الخاصة بالمدير لعرض قائمة المستخدمين المسجلين وأرقام هواتفهم:"
        )
        send_telegram_message(chat_id, prompt_msg)
        return

    # 2. Start / Help Commands
    if normalized_text in ['/start', 'start', '/help', 'help', '❓ مساعدة', 'مساعدة']:
        welcome_msg = (
            "👋 <b>مرحباً بك في بوت إدارة بوابة نتائج ومحاضرات الهندسة المعلوماتية</b>\n"
            "🏛 <i>كلية الهندسة المعلوماتية - جامعة دمشق</i>\n\n"
            "📌 <b>الأوامر المتاحة:</b>\n"
            "• أرسل <b>اريد المستخدمين</b>: لعرض كافة الطلاب والمستخدمين المسجلين وأرقام هواتفهم (يتطلب إدخال كلمة السر <code>2004</code>).\n"
            "• أرسل <b>احصائيات</b>: لعرض ملخص أرقام وقاعدة بيانات البوابة.\n\n"
            "اختر من الأزرار بالأسفل للبدء:"
        )
        send_telegram_message(chat_id, welcome_msg, reply_markup=get_main_keyboard())
        return

    # 3. System Statistics
    if any(s in raw_text for s in ['احصائيات', 'إحصائيات', 'احصاء', '/stats', 'stats', '📊 احصائيات المنظومة']):
        _send_system_stats(chat_id)
        return

    # Default fallback response
    fallback_msg = (
        "مرحباً بك! 👋\n"
        "لطلب قائمة المستخدمين وأرقام هواتفهم، أرسل: <b>اريد المستخدمين</b>\n"
        "أو اضغط على الزر بالأسفل:"
    )
    send_telegram_message(chat_id, fallback_msg, reply_markup=get_main_keyboard())


def _send_users_list(chat_id):
    """Fetches all users from DB and sends them to the chat in formatted chunks."""
    try:
        from accounts.models import User
        users = list(User.objects.all().order_by('-date_joined'))
        total_count = len(users)

        if total_count == 0:
            send_telegram_message(
                chat_id,
                "ℹ️ لا يوجد أي مستخدمين مسجلين في المنظومة حتى الآن.",
                reply_markup=get_main_keyboard()
            )
            return

        header = (
            "✅ <b>تم التحقق بنجاح! كلمة السر صحيحة.</b>\n\n"
            f"👥 <b>قائمة المستخدمين المسجلين في المنظومة</b>\n"
            f"📊 <b>إجمالي عدد المسجلين:</b> <code>{total_count}</code> مستخدم\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
        )

        entries = []
        for idx, u in enumerate(users, 1):
            name = u.full_name or u.username or "طالب غير مسمى"
            phone = u.phone_number or u.username or "غير محدد"
            joined_date = u.date_joined.strftime("%Y-%m-%d %H:%M") if u.date_joined else "غير مسجل"
            email_info = f"\n📧 <b>البريد:</b> <code>{u.email}</code>" if u.email else ""
            student_id_info = f"\n🎓 <b>الرقم الجامعي:</b> <code>{u.linked_student_id}</code>" if u.linked_student_id else ""

            entry = (
                f"<b>{idx}.</b> 👤 <b>الاسم:</b> {name}\n"
                f"📱 <b>الهاتف:</b> <code>{phone}</code>"
                f"{student_id_info}"
                f"{email_info}\n"
                f"📅 <b>تاريخ التسجيل:</b> {joined_date}\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
            )
            entries.append(entry)

        # Telegram message maximum length is 4096 characters.
        # Send header first, then accumulate entries in chunks of up to 3500 chars.
        current_chunk = header
        for entry in entries:
            if len(current_chunk) + len(entry) > 3600:
                send_telegram_message(chat_id, current_chunk)
                current_chunk = entry
            else:
                current_chunk += entry

        if current_chunk:
            send_telegram_message(chat_id, current_chunk, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"[TELEGRAM ERROR] Failed to retrieve users: {e}")
        send_telegram_message(
            chat_id,
            f"⚠️ حدث خطأ أثناء استرجاع بيانات المستخدمين: {e}",
            reply_markup=get_main_keyboard()
        )


def _send_system_stats(chat_id):
    """Sends overview statistics about the database."""
    try:
        from accounts.models import User
        from marks.models import StudentCourseMark, LectureFile, Subject

        users_count = User.objects.count()
        marks_count = StudentCourseMark.objects.count()
        lectures_count = LectureFile.objects.count()
        subjects_count = Subject.objects.count()

        stats_msg = (
            "📊 <b>إحصائيات بوابة الهندسة المعلوماتية</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>عدد المستخدمين المسجلين:</b> {users_count}\n"
            f"📝 <b>إجمالي سجلات العلامات:</b> {marks_count:,}\n"
            f"📚 <b>عدد ملفات المحاضرات:</b> {lectures_count}\n"
            f"🏛 <b>عدد المقررات الدراسية:</b> {subjects_count}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>حالة السيرفر:</b> متصل ونشط 100%\n"
            "☁️ <b>التخزين السحابي:</b> Google Drive & Render Live"
        )
        send_telegram_message(chat_id, stats_msg, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram_message(chat_id, f"⚠️ تعذر جلب الإحصائيات: {e}")


def set_telegram_webhook(webhook_url: str):
    """Registers the public webhook URL with Telegram Bot API."""
    bot_token, _ = get_bot_credentials()
    if not bot_token:
        return False, "Bot token not configured"

    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {"url": webhook_url}

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('ok', False), data.get('description', '')
    except Exception as e:
        return False, str(e)


def delete_telegram_webhook():
    """Deletes the webhook to allow getUpdates polling if needed."""
    bot_token, _ = get_bot_credentials()
    if not bot_token:
        return False, "Bot token not configured"

    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('ok', False), data.get('description', '')
    except Exception as e:
        return False, str(e)
