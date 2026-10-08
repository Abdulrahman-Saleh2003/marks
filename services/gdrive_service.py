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


MARKS_DRIVE_SUBFOLDERS = [
    ("السنة الأولى", 1, "1N_nGm8d9QfQ67bbnkEybNDITJL2iV_ct"),
    ("السنة الثانية", 2, "1T_9q6T0VyNXwio6ERw0G996kUbshN6Ni"),
    ("السنة الثالثة", 3, "1WplY-u3_DqX-KLfW4v9zQOVmUCufJ7pl"),
    ("السنة الرابعة", 4, "1Rz_jrreVuWeWPutESipaHEKhvaOVsIUS"),
    ("السنة الخامسة", 5, "1tN0ULcQYgLETit11VNQM9bRrAoynYvfk"),
]

STATUS_TOKENS = {'راسب', 'ناجح', 'بسار', 'حجان', 'محروم', 'غياب', 'حرمان', 'منقول'}


def norm_mark_s(s):
    s = re.sub(r'(?:^|[\s_])ال', ' ', s)
    return s.replace(' ', '').replace('ة', 'ه').replace('إ', 'ا').replace('أ', 'ا').replace('آ', 'ا').replace('ى', 'ي')


def resolve_course_for_file(fname, year_num):
    fn = fname.replace('.pdf', '').strip()
    n = norm_mark_s(fn)

    if 'حساباتعلميه' in n:
        return 'الحسابات العلمية', 3
    if 'مشروعتخرج' in n:
        return 'مشروع تخرج', 5
    if 'مشروعمترجمات' in n:
        return 'مشروع المترجمات', 4
    if 'مشروعسنهثالثه' in n or ('مشروع' in n and year_num == 3):
        return 'مشروع 1', 3
    if 'مشروع2' in n or ('مشروع' in n and year_num == 4):
        return 'مشروع 2', 4

    if 'تحليل1' in n:
        return 'التحليل 1', 1
    if 'تحليل2' in n:
        return 'التحليل 2', 1
    if 'تحليل3' in n:
        return 'التحليل 3', 2
    if 'عددي' in n:
        return 'التحليل العددي', 2

    if 'برمجه1' in n:
        return 'البرمجة 1', 1
    if 'برمجه2' in n:
        return 'البرمجة 2', 1
    if 'برمجه3' in n:
        return 'البرمجة 3', 2
    if 'تفرعيه' in n:
        return 'البرمجة التفرعية', 4

    if 'خوارزميات1' in n:
        return 'الخوارزميات و بنى المعطيات 1', 2
    if 'خوارزميات2' in n:
        return 'الخوارزميات و بنى المعطيات 2', 2
    if 'خوارزمياتبحث' in n:
        return 'خوارزميات البحث الذكية', 4

    if 'جبرعام' in n:
        return 'الجبر العام', 1
    if 'جبرخطي' in n:
        return 'الجبر الخطي', 1

    if 'داراتكهربائيه' in n:
        return 'الدارات الكهربائية و الالكترونية', 1
    if 'داراتمنطقيه' in n:
        return 'الدارات المنطقية', 2

    if 'فيزياء' in n:
        return 'الفيزياء', 1
    if 'عربيه' in n:
        return 'اللغة العربية', 1
    if 'ثقافه' in n:
        return 'الثقافة القومية الاشتراكية', 1
    if 'عملحواسيب' in n or 'عملحاسب' in n:
        return 'مبادئ عمل الحواسيب', 1

    if 'اتصال' in n or 'اتصاال' in n:
        return 'الاتصالات الرقمية', 2
    if 'احتماالت' in n or 'احتمالات' in n or 'احصاء' in n:
        return 'الاحتمالات و الاحصاء', 2
    if 'بنيانحواسيب1' in n:
        return 'بنيان الحواسيب 1', 2
    if 'بنيانحواسيب2' in n:
        return 'بنيان الحواسيب 2', 3
    if 'مهارات' in n:
        return 'مهارات التواصل', 2

    if 'انكليزي1' in n:
        return 'انكليزي 1', 1
    if 'انكليزي2' in n:
        return 'انكليزي 2', 1
    if 'انكليزي3' in n:
        return 'انكليزي 3', 2
    if 'انكليزي4' in n:
        return 'انكليزي 4', 2

    if 'ادارهشبكات' in n:
        return 'إدارة الشبكات الحاسوبية', 5
    if 'شبكاتحاسوبيه' in n or 'اساسياتشبكات' in n or 'اساسياتالشبكات' in n:
        return 'أساسيات الشبكات', 3
    if 'صوريه' in n:
        return 'اللغات الصورية', 3
    if 'بحوثعمليات' in n:
        return 'بحوث العمليات', 3
    if 'قواعدمعطيات1' in n:
        return 'قواعد المعطيات 1', 3
    if 'قواعدمعطيات2' in n:
        return 'قواعد المعطيات 2', 4
    if 'قواعدمعطياتمتقدمه' in n:
        return 'قواعد المعطيات المتقدمة', 5
    if 'لغاتبرمجه' in n:
        return 'لغات البرمجة', 3
    if 'مبادئذكاء' in n:
        return 'مبادئ الذكاء الصنعي', 3
    if 'بيانيات' in n:
        return 'البيانيات', 3

    if 'اقتصاد' in n:
        return 'الاقتصاد و الإدارة في مؤسسة', 4
    if 'تسويق' in n:
        return 'التسويق', 4
    if 'مترجمات' in n:
        return 'المترجمات', 4
    if 'وسائط' in n:
        return 'نظم الوسائط المتعددة', 4
    if 'تشغيل1' in n:
        return 'نظم تشغيل 1', 4
    if 'تشغيل2' in n:
        return 'نظم التشغيل 2', 4
    if 'هندسه1' in n or 'هندسهبرمجيات1' in n:
        return 'هندسة البرمجيات 1', 4
    if 'هندسه2' in n or 'هندسهبرمجيات2' in n:
        return 'هندسة البرمجيات 2', 4
    if 'هندسه3' in n or 'هندسهبرمجيات3' in n:
        return 'هندسة البرمجيات 3', 5
    if 'هندسهنظم' in n:
        return 'هندسة نظم المعلومات', 5
    if 'حقائق' in n:
        return 'الحقائق الافتراضية', 4
    if 'عصبونيه' in n:
        return 'الشبكات العصبونية', 4
    if 'قواعدمعرفه' in n:
        return 'نظم قواعد المعرفة', 4
    if 'بروتوكو' in n or 'برتوكو' in n:
        return 'برتوكولات الاتصالات الحاسوبية', 4
    if 'تطبيقاتشبكيه' in n:
        return 'برمجة التطبيقات الشبكية', 4

    if 'امنشبكات' in n:
        return 'أمن الشبكات الحاسوبية', 5
    if 'امننظم' in n:
        return 'أمن نظم معلومات', 5
    if 'روبوتيه' in n:
        return 'الروبوتية', 5
    if 'ادارهمشاريع' in n:
        return 'إدارة المشاريع', 5
    if 'استكشاف' in n:
        return 'استكشاف المعرفة', 5
    if 'تعلمتلقائي' in n:
        return 'التعلم التلقائي', 5
    if 'تصميمشبكات' in n:
        return 'تصميم الشبكات الحاسوبية', 5
    if 'تطبيقاتانترنت' in n:
        return 'تطبيقات الانترنت', 5
    if 'رؤيا' in n:
        return 'الرؤيا الحاسوبية', 5
    if 'لغاتطبيعيه' in n:
        return 'معالجة اللغات الطبيعية', 5
    if 'منطقترجيحي' in n:
        return 'المنطق الترجيحي و الخوارزميات الوراثية', 5
    if 'بحثعنمعلومات' in n:
        return 'نظم البحث عن المعلومات', 5
    if 'موزعه' in n:
        return 'النظم و التطبيقات الموزعة', 5
    if 'زمنحقيقي' in n:
        return 'نظم الزمن الحقيقي', 5
    if 'نمذجه' in n or 'محاكاه' in n:
        return 'نمذجة و محاكاة النظم الشبكية', 5

    return fn, year_num


def parse_pdf_mark_row(row):
    clean_row = [str(c).replace('\n', ' ').strip() if c else '' for c in row]
    if not any(clean_row) or len(clean_row) < 5:
        return None

    row_str = " ".join(clean_row)
    if any(h in row_str for h in ["جامعة دمشق", "الدرجة النهائية", "اسم الطالب", "الرقم", "كلية الهندسة", "العالمة كتابة", "الدرجة رقما"]):
        return None

    if re.match(r'^\d{3,10}$', clean_row[-1]):
        pass
    elif re.match(r'^\d{3,10}$', clean_row[0]):
        clean_row = clean_row[::-1]
    else:
        return None

    sid = clean_row[-1]
    student_cand = decode_pdf_arabic(clean_row[-2]).strip()
    father_cand = decode_pdf_arabic(clean_row[-3]).strip()

    if student_cand in STATUS_TOKENS or not student_cand:
        return None
    if father_cand in STATUS_TOKENS:
        father_cand = ""

    if father_cand and father_cand not in student_cand:
        full_name = f"{father_cand} {student_cand}".strip()
    else:
        full_name = student_cand

    def parse_num(val):
        if not val:
            return 0.0
        v_clean = str(val).replace('\n', ' ').strip()
        nums = re.findall(r'\b\d+(?:\.\d+)?\b', v_clean)
        if nums:
            try:
                v = float(nums[0])
                if 0.0 <= v <= 100.0:
                    return v
            except ValueError:
                pass
        return 0.0

    if len(clean_row) == 6:
        total = parse_num(clean_row[-4])
        prac = 0.0
        theo = total
    else:
        total = parse_num(clean_row[-6])
        prac = parse_num(clean_row[-5])
        theo = parse_num(clean_row[-4])
        if total == 0.0 and (prac > 0.0 or theo > 0.0):
            total = min(100.0, prac + theo)

    res_status = "ناجح" if total >= 60.0 else "راسب"
    return {
        "sid": sid,
        "name": full_name,
        "clean_name": normalize_arabic(full_name),
        "total": total,
        "prac": prac,
        "theo": theo,
        "status": res_status,
        "is_grace": (total in [58.0, 59.0])
    }


def sync_google_drive():
    """
    Polls marks Google Drive folder (and its 5 study-year subfolders),
    downloads new PDFs, decodes text accurately, and ingests into database.
    """
    import io
    import time
    import pdfplumber
    from marks.models import GDriveSyncLog, Course, ExamSession, StudentMark, AcademicYear

    total_records = 0
    synced_files = []
    affected_students = set()

    # Gather targets: 5 subfolders + root
    target_folders = list(MARKS_DRIVE_SUBFOLDERS)
    target_folders.append(("الجذر", 1, MARKS_DRIVE_FOLDER_ID))

    for folder_label, default_year, folder_id in target_folders:
        folder_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
        try:
            resp = SESSION.get(folder_url, headers=HEADERS, timeout=25)
            if resp.status_code != 200:
                continue
        except Exception:
            continue

        matches = re.findall(r'id="entry-([^"]+)".*?class="flip-entry-title"[^>]*>([^<]+)<', resp.text)
        if not matches:
            matches = re.findall(r'data-id="([a-zA-Z0-9_-]+)".*?class="flip-entry-title"[^>]*>([^<]+)<', resp.text)

        pdf_files = [(m[0], m[1].strip()) for m in matches if m[1].lower().endswith(".pdf")]

        for file_id, file_name in pdf_files:
            if GDriveSyncLog.objects.filter(file_id=file_id, status="SUCCESS").exists():
                continue

            download_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0"
            content = None
            for _ in range(3):
                try:
                    r = SESSION.get(download_url, headers=HEADERS, timeout=45)
                    if r.status_code == 200 and len(r.content) > 1000:
                        content = r.content
                        break
                except Exception:
                    time.sleep(1)

            if not content:
                continue

            cname, cyear = resolve_course_for_file(file_name, default_year)
            ay, _ = AcademicYear.objects.get_or_create(id=cyear, defaults={"name": f"Year {cyear}"})
            course, _ = Course.objects.get_or_create(name=cname, defaults={"academic_year": ay, "semester": 2})
            if course.academic_year_id != cyear:
                course.academic_year = ay
                course.save()

            exam_session, _ = ExamSession.objects.get_or_create(
                course=course,
                academic_year_str="2025-2026",
                semester_num=2,
                defaults={
                    "session_title": f"{course.name} - 2025-2026 الفصل الثاني",
                    "source_type": "GDRIVE_2026"
                }
            )

            marks_batch = []
            try:
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    for page in pdf.pages:
                        table = page.extract_table()
                        if not table:
                            continue
                        for row in table:
                            parsed = parse_pdf_mark_row(row)
                            if not parsed:
                                continue
                            marks_batch.append(
                                StudentMark(
                                    session=exam_session,
                                    student_university_id=parsed["sid"],
                                    student_name=parsed["name"],
                                    student_name_clean=parsed["clean_name"],
                                    practical_mark=parsed["prac"],
                                    theoretical_mark=parsed["theo"],
                                    total_mark=parsed["total"],
                                    result_status=parsed["status"],
                                    is_grace_eligible=parsed["is_grace"]
                                )
                            )
            except Exception as ex:
                print(f"[GDrive Sync Error] {file_name}: {ex}")

            imported_count = 0
            if marks_batch:
                existing_ids = set(StudentMark.objects.filter(session=exam_session).values_list('student_university_id', flat=True))
                to_create = [m for m in marks_batch if m.student_university_id not in existing_ids]
                if to_create:
                    StudentMark.objects.bulk_create(to_create)
                    imported_count = len(to_create)
                    for m in to_create:
                        affected_students.add(m.student_name_clean)

            GDriveSyncLog.objects.update_or_create(
                file_id=file_id,
                defaults={
                    "file_name": file_name,
                    "records_count": imported_count,
                    "status": "SUCCESS"
                }
            )
            synced_files.append(file_name)
            total_records += imported_count

    if affected_students:
        try:
            update_profiles_for_students(list(affected_students))
        except Exception as ex:
            print(f"[Auto-Profile Update] Notice: {ex}")

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
