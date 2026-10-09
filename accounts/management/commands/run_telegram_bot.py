import time
import urllib.request
import json
import logging
from django.core.management.base import BaseCommand
from services.telegram_service import (
    get_bot_credentials,
    handle_telegram_update,
    delete_telegram_webhook
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs the Telegram Bot in polling mode to receive and reply to user messages."

    def handle(self, *args, **options):
        bot_token, default_chat_id = get_bot_credentials()
        if not bot_token:
            self.stderr.write(self.style.ERROR("TELEGRAM_BOT_TOKEN is not configured! Check .env or settings.py"))
            return

        self.stdout.write(self.style.SUCCESS(f"Starting Telegram Bot Polling (@Ite_marks_abd_bot)..."))
        self.stdout.write(self.style.WARNING("Removing any existing webhook to enable polling..."))
        ok, msg = delete_telegram_webhook()
        self.stdout.write(f"Webhook reset status: ok={ok}, {msg}")

        offset = 0
        self.stdout.write(self.style.SUCCESS("Bot is listening for messages. Press Ctrl+C to stop."))

        while True:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={offset}&timeout=20"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode('utf-8'))

                if not data.get('ok'):
                    time.sleep(2)
                    continue

                updates = data.get('result', [])
                for update in updates:
                    update_id = update.get('update_id')
                    offset = max(offset, update_id + 1)

                    message = update.get('message', {})
                    text = message.get('text', '')
                    sender = message.get('from', {}).get('first_name', 'Unknown')
                    chat_id = message.get('chat', {}).get('id')

                    self.stdout.write(f"[UPDATE] From: {sender} (Chat: {chat_id}) -> '{text}'")
                    handle_telegram_update(update)

            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Stopping Telegram Bot polling."))
                break
            except Exception as e:
                self.stderr.write(f"[ERROR in Bot Polling] {e}")
                time.sleep(3)
