import threading
import time
import os
from django.apps import AppConfig


class MarksConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'marks'

    def ready(self):
        # Start background Google Drive marks sync watcher thread
        # Checks Google Drive every 3 minutes and auto-ingests newly uploaded marks
        is_reloader = os.environ.get('RUN_MAIN') == 'true'
        is_production = 'gunicorn' in os.environ.get('SERVER_SOFTWARE', '').lower() or os.environ.get('RENDER')

        if is_reloader or is_production:
            self.start_gdrive_watcher()

    def start_gdrive_watcher(self):
        def watcher_loop():
            time.sleep(20)  # Initial grace period after server start
            while True:
                try:
                    from services.gdrive_service import sync_google_drive
                    res = sync_google_drive()
                    if res and res.get('new_files', 0) > 0:
                        print(f"[Auto-GDrive] Synced {res['new_files']} new files ({res.get('records', 0)} marks).")
                except Exception as e:
                    print(f"[Auto-GDrive] Watcher notice: {e}")
                time.sleep(180)  # Poll every 3 minutes

        t = threading.Thread(target=watcher_loop, daemon=True, name="GDriveMarksWatcher")
        t.start()
