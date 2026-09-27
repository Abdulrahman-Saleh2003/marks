"""
WSGI config for project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')

import gzip
import shutil
from pathlib import Path

# Auto-extract preloaded database from compressed gzip if missing
base_dir = Path(__file__).resolve().parent.parent
db_file = base_dir / 'db.sqlite3'
gz_file = base_dir / 'db.sqlite3.gz'
if gz_file.exists() and (not db_file.exists() or db_file.stat().st_size < 10 * 1024 * 1024 or gz_file.stat().st_mtime > db_file.stat().st_mtime):
    print(f"[Auto-Database] Extracting {gz_file.name} to {db_file.name}...")
    with gzip.open(gz_file, 'rb') as f_in, open(db_file, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    print(f"[Auto-Database] Extracted {db_file.name} successfully ({db_file.stat().st_size / (1024*1024):.1f} MB)!")

application = get_wsgi_application()
