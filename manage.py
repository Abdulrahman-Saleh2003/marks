#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # Auto-extract preloaded database from compressed gzip if missing
    import gzip, shutil
    from pathlib import Path
    base_dir = Path(__file__).resolve().parent
    db_file = base_dir / 'db.sqlite3'
    gz_file = base_dir / 'db.sqlite3.gz'
    if gz_file.exists() and (not db_file.exists() or db_file.stat().st_size < 10 * 1024 * 1024 or gz_file.stat().st_mtime > db_file.stat().st_mtime):
        print(f"[Auto-Database] Extracting {gz_file.name} to {db_file.name}...")
        with gzip.open(gz_file, 'rb') as f_in, open(db_file, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        print(f"[Auto-Database] Extracted {db_file.name} successfully ({db_file.stat().st_size / (1024*1024):.1f} MB)!")

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
