import re
import requests
from .arabic_service import decode_pdf_arabic, normalize_arabic


LECTURES_DRIVE_FOLDER_ID = "0BwGBqPXoFMyUcEo4bTRrZzVKVDg"
LECTURES_RESOURCE_KEY = "0-m7_x4KXX8ab9SF2gvt6IdA"

MARKS_DRIVE_FOLDER_ID = "1qqccO6X9bQd0ROdovS-QRdLa9Oj2ZbYN"

SESSION = requests.Session()
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

YEAR_NAME_MAP = {
    "السنة الأولى": 1,
    "السنة الثانية": 2,
    "السنة الثالثة": 3,
    "السنة الرابعة": 4,
    "السنة الخامسة": 5,
    "السنة الخامسة ": 5,  # with trailing space
    "أولى": 1, "ثانية": 2, "ثالثة": 3, "رابعة": 4, "خامسة": 5,
}


def _get_drive_folder_entries(folder_id, resource_key=None):
    """Scrape Google Drive embedded folder view to get list of entries (folders/files)."""
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}"
    if resource_key:
        url += f"&resourcekey={resource_key}"
    url += "#list"

    try:
        resp = SESSION.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    html = resp.text
    entries = []

    # Parse entry IDs and titles
    entry_pattern = re.compile(
        r'id="entry-([a-zA-Z0-9_-]+)".*?flip-entry-title[^>]*>(.*?)</div>.*?'
        r'flip-entry-last-modified[^>]*>.*?<div>(.*?)</div>',
        re.DOTALL
    )
    for m in entry_pattern.finditer(html):
        entry_id = m.group(1)
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        last_modified = m.group(3).strip()
        if title:
            entries.append({
                "id": entry_id,
                "title": title,
                "last_modified": last_modified,
                "is_folder": 'drive-sprite-folder' in m.group(0) or 'folder' in m.group(0).lower(),
            })

    # Alternative parse: href-based approach
    if not entries:
        alt_pattern = re.compile(
            r'href="https://drive.google.com/drive/folders/([a-zA-Z0-9_-]+)[^"]*"[^>]*>.*?'
            r'flip-entry-title[^>]*>(.*?)</div>',
            re.DOTALL
        )
        for m in alt_pattern.finditer(html):
            folder_id_found = m.group(1)
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if title:
                entries.append({
                    "id": folder_id_found,
                    "title": title,
                    "last_modified": "",
                    "is_folder": True,
                })

    return entries


def sync_lectures_from_drive():
    """
    Crawl the Google Drive lectures folder tree and populate the database.
    Structure: Root → Academic Years → Study Years → Subjects → Lecture Files
    Returns sync summary dict.
    """
    from marks.models import (
        LectureAcademicYear, LectureStudyYear, LectureSubject, Lecture
    )

    summary = {
        "status": "SUCCESS",
        "academic_years": 0,
        "study_years": 0,
        "subjects": 0,
        "lectures": 0,
        "new_lectures": 0,
        "errors": []
    }

    # Step 1: Get all academic year folders from root
    root_entries = _get_drive_folder_entries(LECTURES_DRIVE_FOLDER_ID, LECTURES_RESOURCE_KEY)
    if not root_entries:
        summary["status"] = "ERROR"
        summary["errors"].append("Could not read root lectures folder")
        return summary

    for ay_entry in root_entries:
        if not ay_entry.get("is_folder", True):
            continue

        # Match academic year pattern like "محاضرات العام 2024-2025"
        title = ay_entry["title"]
        year_match = re.search(r'(\d{4}-\d{4})', title)
        if not year_match:
            continue

        year_label = year_match.group(1)
        ay_folder_id = ay_entry["id"]
        ay_url = f"https://drive.google.com/drive/folders/{ay_folder_id}"

        # Get or create academic year record
        ay_obj, _ = LectureAcademicYear.objects.update_or_create(
            year_label=year_label,
            defaults={
                "drive_folder_id": ay_folder_id,
                "drive_folder_url": ay_url
            }
        )
        summary["academic_years"] += 1

        # Step 2: Get study year folders inside this academic year
        sy_entries = _get_drive_folder_entries(ay_folder_id)
        for sy_entry in sy_entries:
            if not sy_entry.get("is_folder", True):
                continue

            sy_title = sy_entry["title"].strip()
            sy_folder_id = sy_entry["id"]
            sy_url = f"https://drive.google.com/drive/folders/{sy_folder_id}"

            # Map Arabic year name to number
            year_num = None
            for name_key, num in YEAR_NAME_MAP.items():
                if name_key in sy_title:
                    year_num = num
                    break
            if year_num is None:
                # Try matching digits in the title
                num_match = re.search(r'([١٢٣٤٥]|[1-5])', sy_title)
                if num_match:
                    arabic_to_num = {"١": 1, "٢": 2, "٣": 3, "٤": 4, "٥": 5}
                    char = num_match.group(1)
                    year_num = arabic_to_num.get(char, int(char) if char.isdigit() else None)
            if year_num is None:
                continue

            sy_obj, _ = LectureStudyYear.objects.update_or_create(
                academic_year=ay_obj,
                year_number=year_num,
                defaults={
                    "year_name": sy_title,
                    "drive_folder_id": sy_folder_id,
                    "drive_folder_url": sy_url
                }
            )
            summary["study_years"] += 1

            # Step 3: Get subject folders inside study year
            subj_entries = _get_drive_folder_entries(sy_folder_id)
            for subj_entry in subj_entries:
                if not subj_entry.get("is_folder", True):
                    continue

                subj_title = subj_entry["title"].strip()
                subj_folder_id = subj_entry["id"]
                subj_url = f"https://drive.google.com/drive/folders/{subj_folder_id}"

                subj_obj, _ = LectureSubject.objects.update_or_create(
                    study_year=sy_obj,
                    subject_name=subj_title,
                    defaults={
                        "drive_folder_id": subj_folder_id,
                        "drive_folder_url": subj_url
                    }
                )
                summary["subjects"] += 1

                # Step 4: Get lecture files inside subject
                lecture_entries = _get_drive_folder_entries(subj_folder_id)
                for lec_entry in lecture_entries:
                    lec_file_id = lec_entry["id"]
                    lec_title = lec_entry["title"].strip()

                    if not lec_title:
                        continue

                    # Determine file type
                    file_ext = ""
                    if "." in lec_title:
                        file_ext = lec_title.rsplit(".", 1)[-1].lower()

                    view_url = f"https://drive.google.com/file/d/{lec_file_id}/view"
                    download_url = f"https://drive.usercontent.google.com/download?id={lec_file_id}&export=download"

                    _, created = Lecture.objects.update_or_create(
                        drive_file_id=lec_file_id,
                        defaults={
                            "subject": subj_obj,
                            "title": lec_title,
                            "drive_view_url": view_url,
                            "drive_download_url": download_url,
                            "file_type": file_ext,
                            "date_uploaded": lec_entry.get("last_modified", ""),
                        }
                    )
                    summary["lectures"] += 1
                    if created:
                        summary["new_lectures"] += 1

    return summary


def get_lectures_tree(year_label=None, study_year_num=None):
    """
    Get the lectures tree as a JSON-serializable dict.
    Can be filtered by academic year or study year.
    """
    from marks.models import LectureAcademicYear, LectureStudyYear, LectureSubject, Lecture

    qs = LectureAcademicYear.objects.prefetch_related(
        'study_years__subjects__lectures'
    ).order_by('-year_label')

    if year_label:
        qs = qs.filter(year_label=year_label)

    result = []
    for ay in qs:
        ay_data = {
            "year_label": ay.year_label,
            "drive_folder_url": ay.drive_folder_url,
            "study_years": []
        }
        study_years_qs = ay.study_years.all()
        if study_year_num:
            study_years_qs = study_years_qs.filter(year_number=study_year_num)

        for sy in study_years_qs:
            sy_data = {
                "year_number": sy.year_number,
                "year_name": sy.year_name,
                "drive_folder_url": sy.drive_folder_url,
                "subjects": []
            }
            for subj in sy.subjects.all():
                subj_data = {
                    "subject_name": subj.subject_name,
                    "drive_folder_url": subj.drive_folder_url,
                    "lectures": [
                        {
                            "id": lec.id,
                            "title": lec.title,
                            "file_type": lec.file_type,
                            "drive_view_url": lec.drive_view_url,
                            "drive_download_url": lec.drive_download_url,
                            "date_uploaded": lec.date_uploaded,
                        }
                        for lec in subj.lectures.all()
                    ]
                }
                sy_data["subjects"].append(subj_data)
            ay_data["study_years"].append(sy_data)
        result.append(ay_data)

    return result


def sync_google_drive():
    """
    Polls marks Google Drive folder, downloads new PDFs, decodes text, and ingests into database.
    """
    import os
    import pdfplumber
    from django.conf import settings
    from marks.models import GDriveSyncLog, Course, ExamSession, StudentMark, AcademicYear

    folder_id = getattr(settings, 'GDRIVE_FOLDER_ID', MARKS_DRIVE_FOLDER_ID)
    folder_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"

    resp = SESSION.get(folder_url, headers=HEADERS, timeout=20)
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
        file_resp = SESSION.get(download_url, headers=HEADERS, stream=True, timeout=60)
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
                try:
                    update_profiles_for_students([m.student_name_clean for m in marks_batch])
                except Exception as ex:
                    print(f"[Auto-Profile] Notice: {ex}")

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


def update_profiles_for_students(clean_names):
    """
    Incrementally updates the StudentProfile inverted index for the given student names.
    Ensures that newly imported Google Drive marks are reflected in search and analytics immediately.
    """
    from marks.models import StudentMark, StudentProfile
    from marks.views import build_student_years_summary

    unique_names = set(clean_names)
    for cn in unique_names:
        if not cn:
            continue
        marks_qs = StudentMark.objects.filter(student_name_clean=cn).select_related('session__course', 'session')
        if not marks_qs.exists():
            continue

        sample = marks_qs.first()
        student_name = sample.student_name

        all_seats = sorted(list(set(
            m.student_university_id for m in marks_qs
            if m.student_university_id and not m.student_university_id.startswith('2025_')
        )))
        primary_id = max(all_seats, key=lambda x: (len(x), x)) if all_seats else (sample.student_university_id or "")

        years_out, cum_gpa, progress_chart = build_student_years_summary(marks_qs)

        passed_count = sum(y.get('passed_count', 0) for y in years_out)
        carried_count = sum(y.get('carried_count', 0) for y in years_out)
        unattempted_count = sum(y.get('unattempted_count', 0) for y in years_out)
        total_count = sum(y.get('total_courses', 0) for y in years_out)

        inverted_map = {}
        for y in years_out:
            for p in y.get('passed_courses', []):
                inverted_map[p['course_name']] = p['final_score']
            for c in y.get('carried_courses', []):
                inverted_map[c['course_name']] = c['last_score']
            for u in y.get('unattempted_courses', []):
                inverted_map[u['course_name']] = 0.0

        all_scores = [p['final_score'] for y in years_out for p in y.get('passed_courses', [])] + \
                     [c['last_score'] for y in years_out for c in y.get('carried_courses', [])]
        highest_mark = max(all_scores) if all_scores else 0.0
        lowest_mark = min(all_scores) if all_scores else 0.0

        academic_status = "ناجح ومترفع" if carried_count == 0 else f"يحمل {carried_count} مواد متبقية"

        StudentProfile.objects.update_or_create(
            student_name_clean=cn,
            defaults={
                "student_name": student_name,
                "primary_id": primary_id,
                "all_student_ids": all_seats,
                "cumulative_gpa": cum_gpa,
                "passed_courses_count": passed_count,
                "carried_courses_count": carried_count,
                "unattempted_courses_count": unattempted_count,
                "total_courses_count": total_count,
                "highest_mark_overall": highest_mark,
                "lowest_mark_overall": lowest_mark,
                "academic_status": academic_status,
                "years_summary": years_out,
                "courses_inverted_map": inverted_map,
                "progress_chart": progress_chart
            }
        )
