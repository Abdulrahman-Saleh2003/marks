import os
import re
import requests
import pdfplumber
from django.conf import settings
from .arabic_service import decode_pdf_arabic, normalize_arabic


def sync_google_drive():
    """
    Polls Google Drive folder, downloads new PDFs, decodes text, and ingests into database.
    """
    from marks.models import GDriveSyncLog, Course, ExamSession, StudentMark, AcademicYear

    folder_id = getattr(settings, 'GDRIVE_FOLDER_ID', '1qqccO6X9bQd0ROdovS-QRdLa9Oj2ZbYN')
    folder_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    resp = session.get(folder_url, headers=headers, timeout=20)
    if resp.status_code != 200:
        return {"status": "ERROR", "message": f"HTTP {resp.status_code}", "new_files": 0, "records": 0, "files": []}

    matches = re.findall(r'data-id="([a-zA-Z0-9_-]+)".*?class="flip-entry-title"[^>]*>([^<]+)<', resp.text)
    if not matches:
        matches = re.findall(r'id="entry-([a-zA-Z0-9_-]+)".*?<span class="file-name">([^<]+)</span>', resp.text)

    synced_files = []
    total_records = 0

    for file_id, file_name in matches:
        if not file_name.lower().endswith(".pdf"):
            continue

        clean_name = decode_pdf_arabic(file_name) if "اال" in file_name or "ة" in file_name else file_name

        if GDriveSyncLog.objects.filter(file_id=file_id).exists():
            continue

        download_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0"
        file_resp = session.get(download_url, headers=headers, stream=True, timeout=60)
        if file_resp.status_code != 200:
            continue

        temp_pdf = f"temp_gdrive_{file_id}.pdf"
        with open(temp_pdf, "wb") as f:
            for chunk in file_resp.iter_content(32768):
                if chunk: f.write(chunk)

        course_name = clean_name.replace(".pdf", "").replace("نتيجة مادة", "").strip()
        default_year, _ = AcademicYear.objects.get_or_create(id=1, defaults={"name": "First Year"})
        course, _ = Course.objects.get_or_create(name=course_name, defaults={"academic_year": default_year, "semester": 2})

        exam_session = ExamSession.objects.create(
            course=course,
            session_title=f"{course_name} - 2025-2026 الفصل الثاني",
            academic_year_str="2025-2026",
            semester_num=2,
            source_type="GDRIVE"
        )

        imported = 0
        with pdfplumber.open(temp_pdf) as pdf:
            marks_batch = []
            for page in pdf.pages:
                table = page.extract_table()
                if not table: continue
                for row in table[1:]:
                    clean_row = [str(c).strip() if c else "" for c in row]
                    if not any(clean_row): continue

                    sid = ""
                    sname = ""
                    for col in clean_row:
                        if re.match(r"^\d{4,8}$", col) and not sid: sid = col
                        elif re.search(r"[\u0600-\u06FF]", col) and len(col) > 3 and not sname:
                            sname = decode_pdf_arabic(col)

                    nums = []
                    for col in clean_row:
                        try: nums.append(float(col))
                        except ValueError: pass

                    total = max(nums) if nums else 0.0
                    prac = nums[0] if len(nums) >= 2 else 0.0
                    theo = nums[1] if len(nums) > 2 else (total - prac)
                    result = "ناجح" if total >= 60.0 else "راسب"

                    if sname and (sid or total > 0):
                        marks_batch.append(
                            StudentMark(
                                session=exam_session,
                                student_university_id=sid or f"GEN_{imported}",
                                student_name=sname,
                                student_name_clean=normalize_arabic(sname),
                                practical_mark=prac,
                                theoretical_mark=theo,
                                total_mark=total,
                                result_status=result,
                                is_grace_eligible=(total in [58.0, 59.0])
                            )
                        )
                        imported += 1

            if marks_batch:
                StudentMark.objects.bulk_create(marks_batch)

        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)

        GDriveSyncLog.objects.create(
            file_id=file_id,
            file_name=clean_name,
            records_count=imported,
            status="SUCCESS"
        )
        synced_files.append(clean_name)
        total_records += imported

    return {
        "status": "SUCCESS",
        "message": f"Synchronized {len(synced_files)} new files.",
        "new_files": len(synced_files),
        "records": total_records,
        "files": synced_files
    }
