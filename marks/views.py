import re
from collections import defaultdict
from urllib.parse import unquote
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.db.models import Count, Avg, Max, Min, Q
from django.http import HttpResponse

from .models import (
    StudentMark, Course, ExamSession, AcademicYear, Department,
    GDriveSyncLog, StudentProfile,
    LectureAcademicYear, LectureStudyYear, LectureSubject, Lecture
)
from services.arabic_service import calculate_similarity, normalize_arabic
from services.pdf_service import generate_mark_pdf, generate_transcript_pdf
from services.gdrive_service import sync_google_drive, sync_lectures_from_drive, get_lectures_tree


ARABIC_YEAR_NAMES = {
    1: 'السنة الأولى',
    2: 'السنة الثانية',
    3: 'السنة الثالثة',
    4: 'السنة الرابعة',
    5: 'السنة الخامسة'
}


def get_param(request, key, default=""):
    params = getattr(request, 'query_params', None)
    if params is None:
        params = getattr(request, 'GET', {})
    val = params.get(key, default)
    return str(val).strip() if val is not None else default


def format_student_name(name):
    if not name:
        return ""
    name = name.strip()
    name = re.sub(r'^(?:[\u064a\u0648\u0627\u062f])\s+', '', name)
    name = re.sub(r'^(?:محروم|غياب|وعشرون|اثنتا|اثنان|ثلاثون|أربعون|خمسون|ستون|سبعون|ثمانون|تسعون)\s+', '', name)
    replacements = {
        'دمحم': 'محمد',
        'عالء': 'علاء',
        'سدرا الاعور': 'سيدرا الأعور',
        'سدرا العور': 'سيدرا الأعور',
        'سيدرا العول': 'سيدرا الأعور',
        'بالل': 'بلال',
        'جالل': 'جلال',
        'هالل': 'هلال',
        'طالل': 'طلال',
        'إسالم': 'إسلام',
        'هللا': 'الله',
        'حال حسيان': 'حلا حسيان',
        'سالم نارص': 'سالم ناصر',
    }
    for k, v in replacements.items():
        name = name.replace(k, v)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def clean_tokens(name):
    if not name:
        return []
    s = normalize_arabic(name)
    s = s.replace('عبد ', 'عبد')
    s = s.replace('ابو ', 'ابو')
    s = s.replace('ال دين', 'الدين')
    s = s.replace('ال ح', 'الح')
    s = re.sub(r'^(?:[\u064a\u0648\u0627\u062f])\s+', '', s)
    s = re.sub(r'^(?:محروم|غياب|وعشرون|اثنتا|اثنان|ثلاثون|اربعون|خمسون|ستون|سبعون|ثمانون|تسعون)\s+', '', s)
    tokens = [t for t in s.split() if len(t) >= 2]
    return tokens


def evaluate_syrian_grace_marks(all_carried_courses):
    """
    Evaluates Syrian University Grace Marks (قانون تنظيم الجامعات السورية لعلامات المساعدة):
    Maximum 2 grace marks total per academic year.
    Eligible ONLY if latest attempt was in Semester 2 (الفصل الثاني) and mark is 58 or 59.

    Applicable in ONLY 4 specific scenarios:
    1. Single carried course (N == 1):
       If mark is 58 or 59 in Semester 2 -> Eligible for 2 or 1 mark to complete all courses / graduate.
    2. Two carried courses (N == 2):
       If BOTH courses are 59 in Semester 2 -> Eligible for 1 mark each (1+1=2) to complete all courses / graduate.
    3. Five carried courses (N == 5):
       Student cannot promote (limit <= 4).
       If ONE course is 58 or 59 in Semester 2 -> Eligible for 2 or 1 mark, dropping carried to 4 -> Promoted to next year!
    4. Six carried courses (N == 6):
       Student cannot promote (limit <= 4).
       If TWO courses are 59 in Semester 2 -> Eligible for 1 mark each (1+1=2), dropping carried to 4 -> Promoted to next year!

    In all other cases (e.g. N == 2 with 59 and 53, N in [3, 4], N >= 7, or session not Semester 2):
    NO course is eligible for grace marks.
    """
    for c in all_carried_courses:
        c['is_grace_eligible'] = False
        c['required_grace_marks'] = 0
        c['status'] = 'مادة متبقية (تحتاج إعادة تقديم)'
        c['grace_explanation'] = ''

    total_carried = len(all_carried_courses)

    def is_semester_2(c):
        sem_num = c.get('semester_num', 0)
        title = c.get('session_title', '')
        return sem_num == 2 or ('الثاني' in title) or ('تكميلي' in title) or ('تكميلية' in title)

    sem2_candidates = [c for c in all_carried_courses if is_semester_2(c) and c.get('last_score', 0) in [58.0, 59.0]]

    # Case 1: Exactly 1 carried course with 58 or 59 in semester 2
    if total_carried == 1 and len(sem2_candidates) == 1:
        c = sem2_candidates[0]
        needed = int(60 - c['last_score'])
        c['is_grace_eligible'] = True
        c['required_grace_marks'] = needed
        c['status'] = f"مرفعة مساعدة (تحتاج +{needed} للترفع التام)"
        c['grace_explanation'] = f"مادة مؤهلة لنيل {needed} علامة مساعدة للترفع التام واستكمال كافة المقررات (مرسوم تنظيم الجامعات)."

    # Case 2: Exactly 2 carried courses, and BOTH have 59 in semester 2
    elif total_carried == 2 and len(sem2_candidates) == 2:
        if all(c['last_score'] == 59.0 for c in sem2_candidates):
            for c in sem2_candidates:
                c['is_grace_eligible'] = True
                c['required_grace_marks'] = 1
                c['status'] = "مرفعة مساعدة (تحتاج +1 للترفع التام)"
                c['grace_explanation'] = "مادة مؤهلة لنيل علامة مساعدة واحدة (1+1) للترفع التام واستكمال كافة المقررات (مرسوم تنظيم الجامعات)."

    # Case 3: Exactly 5 carried courses, student needs 1 course to drop to 4 for promotion
    elif total_carried == 5 and len(sem2_candidates) >= 1:
        best_cand = max(sem2_candidates, key=lambda x: x['last_score'])
        needed = int(60 - best_cand['last_score'])
        best_cand['is_grace_eligible'] = True
        best_cand['required_grace_marks'] = needed
        best_cand['status'] = f"مرفعة مساعدة (تحتاج +{needed} للترفع ونيل النقل)"
        best_cand['grace_explanation'] = f"مادة مؤهلة لنيل {needed} علامة مساعدة لخفض المقررات المحمولة إلى 4 والترفع للسنة التالية (مرسوم تنظيم الجامعات)."

    # Case 4: Exactly 6 carried courses, student needs 2 courses with 59 to drop to 4 for promotion
    elif total_carried == 6:
        cands_59 = [c for c in sem2_candidates if c['last_score'] == 59.0]
        if len(cands_59) >= 2:
            for c in cands_59[:2]:
                c['is_grace_eligible'] = True
                c['required_grace_marks'] = 1
                c['status'] = "مرفعة مساعدة (تحتاج +1 للترفع ونيل النقل)"
                c['grace_explanation'] = "مادة مؤهلة لنيل علامة مساعدة واحدة (1+1) لخفض المقررات المحمولة إلى 4 والترفع للسنة التالية (مرسوم تنظيم الجامعات)."

    return all_carried_courses


CURRICULUM_COURSES = {
    1: ['البرمجة 1', 'البرمجة 2', 'التحليل 1', 'التحليل 2', 'الثقافة القومية الاشتراكية', 'الجبر الخطي', 'الجبر العام', 'الدارات الكهربائية و الالكترونية', 'الفيزياء', 'اللغة العربية', 'انكليزي 1', 'انكليزي 2', 'مبادئ عمل الحواسيب'],
    2: ['الاتصالات الرقمية', 'الاحتمالات و الاحصاء', 'البرمجة 3', 'التحليل 3', 'التحليل العددي', 'الخوارزميات و بنى المعطيات 1', 'الخوارزميات و بنى المعطيات 2', 'الدارات المنطقية', 'انكليزي 3', 'انكليزي 4', 'بنيان الحواسيب 1', 'مهارات التواصل'],
    3: ['أساسيات الشبكات', 'البيانيات', 'الحسابات العلمية', 'اللغات الصورية', 'بحوث العمليات', 'بنيان الحواسيب 2', 'قواعد المعطيات 1', 'لغات البرمجة', 'مبادئ الذكاء الصنعي', 'مشروع 1'],
    4: {
        'AI': ['الاقتصاد و الإدارة في مؤسسة', 'البرمجة التفرعية', 'التسويق', 'المترجمات', 'خوارزميات البحث الذكية', 'مشروع 2', 'نظم الوسائط المتعددة', 'نظم تشغيل 1', 'هندسة البرمجيات 1', 'الحقائق الافتراضية', 'الشبكات العصبونية', 'نظم قواعد المعرفة'],
        'SOFTWARE': ['الاقتصاد و الإدارة في مؤسسة', 'البرمجة التفرعية', 'التسويق', 'المترجمات', 'خوارزميات البحث الذكية', 'قواعد المعطيات 2', 'مشروع 2', 'مشروع المترجمات', 'نظم الوسائط المتعددة', 'نظم تشغيل 1', 'هندسة البرمجيات 1', 'هندسة البرمجيات 2'],
        'NETWORKS': ['البرمجة التفرعية', 'التسويق', 'خوارزميات البحث الذكية', 'نظم الوسائط المتعددة', 'نظم تشغيل 1', 'هندسة البرمجيات 1', 'مشروع 2', 'برتوكولات الاتصالات الحاسوبية', 'برمجة التطبيقات الشبكية', 'نظم التشغيل 2']
    },
    5: {
        'AI': ['أمن الشبكات الحاسوبية', 'استكشاف المعرفة', 'التعلم التلقائي', 'الرؤيا الحاسوبية', 'الروبوتية', 'المنطق الترجيحي و الخوارزميات الوراثية', 'معالجة اللغات الطبيعية', 'مشروع تخرج'],
        'SOFTWARE': ['أمن نظم معلومات', 'إدارة المشاريع', 'النظم و التطبيقات الموزعة', 'تطبيقات الانترنت', 'قواعد المعطيات المتقدمة', 'مشروع تخرج', 'نظم البحث عن المعلومات', 'هندسة البرمجيات 3', 'هندسة نظم المعلومات'],
        'NETWORKS': ['أمن الشبكات الحاسوبية', 'إدارة الشبكات الحاسوبية', 'تصميم الشبكات الحاسوبية', 'نظم الزمن الحقيقي', 'نمذجة و محاكاة النظم الشبكية', 'مشروع تخرج']
    }
}


def build_student_years_summary(marks_qs):
    """Groups courses and marks year-by-year with accurate de-duplicated attempt counting, stats and unattempted courses."""
    by_y = {}
    ai_score = 0
    net_score = 0
    for m in marks_qs:
        y_id = (
            m.session.course.academic_year_id
            if m.session.course and m.session.course.academic_year_id
            else (int(m.student_university_id[0]) if m.student_university_id and m.student_university_id[0] in '12345' else 1)
        )
        by_y.setdefault(y_id, []).append(m)
        cname = m.session.course.name if m.session and m.session.course else ""
        if any(k in cname for k in ['عصبونية', 'حقائق', 'قواعد المعرفة', 'التعلم التلقائي', 'رؤيا', 'روبوتية']):
            ai_score += 1
        elif any(k in cname for k in ['برتوكولات', 'تطبيقات شبكية', 'تشغيل 2', 'تصميم شبكات']):
            net_score += 1

    detected_dept = 'AI' if ai_score >= 2 and ai_score >= net_score else ('NETWORKS' if net_score >= 2 else 'SOFTWARE')

    max_year = max(by_y.keys()) if by_y else 1
    for y_idx in range(1, max_year + 1):
        by_y.setdefault(y_idx, [])

    years_out = []
    all_unique_scores = []
    progress_chart_data = []

    for y_id in sorted(by_y.keys()):
        y_name = ARABIC_YEAR_NAMES.get(y_id, f'السنة {y_id}')
        m_list = by_y[y_id]
        courses_map = {}
        for m in m_list:
            if m.session and m.session.course:
                courses_map.setdefault(m.session.course.name, []).append(m)

        passed_courses = []
        carried_courses = []
        year_scores = []
        raw_marks_list = []

        for cname, atts in courses_map.items():
            # De-duplicate attempts by session_title and pick highest mark if duplicate imports
            unique_sessions = {}
            for a in atts:
                stitle = a.session.session_title.strip()
                if stitle not in unique_sessions or a.total_mark > unique_sessions[stitle].total_mark:
                    unique_sessions[stitle] = a

            attempts_list = list(unique_sessions.values())

            # If there's a passing mark, ignore zero-placeholder sessions (e.g. project semester 2 before defense)
            if any(a.total_mark >= 60.0 for a in attempts_list):
                attempts_list = [a for a in attempts_list if a.total_mark > 0.0]

            attempts_count = max(1, len(attempts_list))
            passing = [a for a in attempts_list if a.total_mark >= 60.0]

            if passing:
                best = max(passing, key=lambda x: x.total_mark)
                passed_courses.append({
                    'course_name': cname,
                    'final_score': best.total_mark,
                    'attempts_count': attempts_count,
                    'session_title': best.session.session_title,
                    'academic_year': best.session.academic_year_str,
                    'student_university_id': best.student_university_id,
                    'mark_id': best.id,
                    'status': 'ناجح'
                })
                year_scores.append(best.total_mark)
                all_unique_scores.append(best.total_mark)
            else:
                latest = attempts_list[-1]
                carried_courses.append({
                    'course_name': cname,
                    'last_score': latest.total_mark,
                    'attempts_count': attempts_count,
                    'session_title': latest.session.session_title,
                    'academic_year': latest.session.academic_year_str,
                    'student_university_id': latest.student_university_id,
                    'semester_num': latest.session.semester_num,
                    'mark_id': latest.id,
                    'is_grace_eligible': False,
                    'required_grace_marks': 0,
                    'status': 'مادة متبقية (تحتاج إعادة تقديم)'
                })
                year_scores.append(latest.total_mark)
                all_unique_scores.append(latest.total_mark)

            for a in attempts_list:
                raw_marks_list.append({
                    'id': a.id,
                    'course_name': a.session.course.name,
                    'session_title': a.session.session_title,
                    'academic_year': a.session.academic_year_str,
                    'student_university_id': a.student_university_id,
                    'practical_mark': a.practical_mark if a.practical_mark and a.practical_mark > 0 else None,
                    'theoretical_mark': a.theoretical_mark if a.theoretical_mark and a.theoretical_mark > 0 else None,
                    'total_mark': a.total_mark,
                    'result_status': a.result_status
                })

        # Calculate unattempted curriculum courses
        seat_numbers = sorted(list(set(m.student_university_id for m in m_list if m.student_university_id)))
        default_seat = seat_numbers[0] if seat_numbers else ""
        req_list = CURRICULUM_COURSES.get(y_id, [])
        if isinstance(req_list, dict):
            req_list = req_list.get(detected_dept, req_list.get('SOFTWARE', []))

        def norm_c(s):
            return re.sub(r'^(?:مشروع|مقرر)\s+', '', s).replace('ال', '').replace(' ', '').replace('ة', 'ه').replace('إ', 'ا').replace('أ', 'ا').replace('آ', 'ا')

        unattempted_courses = []
        for rc in req_list:
            n_rc = norm_c(rc)
            attempted = any(n_rc in norm_c(c) or norm_c(c) in n_rc for c in courses_map.keys())
            if not attempted:
                unattempted_courses.append({
                    'course_name': rc,
                    'final_score': 0.0,
                    'last_score': 0.0,
                    'attempts_count': 0,
                    'session_title': '-',
                    'academic_year': '-',
                    'student_university_id': default_seat,
                    'mark_id': None,
                    'status': 'لم يتقدم للمقرر',
                    'is_unattempted': True
                })

        passed_courses.sort(key=lambda x: x['final_score'], reverse=True)
        carried_courses.sort(key=lambda x: x['last_score'], reverse=True)
        year_gpa = round(sum(year_scores) / len(year_scores), 2) if year_scores else 0.0

        # Highest and lowest mark in this specific year
        year_highest_mark = max(year_scores) if year_scores else 0
        year_lowest_mark = min(year_scores) if year_scores else 0
        year_highest_course = next((p['course_name'] for p in passed_courses if p['final_score'] == year_highest_mark), "")
        year_lowest_course = next((c['course_name'] for c in carried_courses if c['last_score'] == year_lowest_mark), "")
        if not year_lowest_course and passed_courses:
            year_lowest_course = min(passed_courses, key=lambda x: x['final_score'])['course_name']

        years_out.append({
            'year_id': y_id,
            'year_name': y_name,
            'seat_number': default_seat,
            'seat_numbers': seat_numbers,
            'annual_gpa': year_gpa,
            'total_courses': len(courses_map) + len(unattempted_courses),
            'passed_count': len(passed_courses),
            'carried_count': len(carried_courses),
            'unattempted_count': len(unattempted_courses),
            'highest_mark': year_highest_mark,
            'highest_course': year_highest_course,
            'lowest_mark': year_lowest_mark,
            'lowest_course': year_lowest_course,
            'passed_courses': passed_courses,
            'carried_courses': carried_courses,
            'unattempted_courses': unattempted_courses,
            'marks': raw_marks_list
        })

        progress_chart_data.append({
            'year_name': y_name,
            'gpa': year_gpa,
            'passed': len(passed_courses),
            'carried': len(carried_courses)
        })

    # Evaluate Syrian University Grace Marks across all carried courses globally
    all_carried_flat = []
    for y in years_out:
        all_carried_flat.extend(y['carried_courses'])
    evaluate_syrian_grace_marks(all_carried_flat)

    cum_gpa = round(sum(all_unique_scores) / len(all_unique_scores), 2) if all_unique_scores else 0.0
    return years_out, cum_gpa, progress_chart_data


class SmartMatchView(APIView):
    """Suggests close matching student identities upon reaching Home screen."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user_name = request.user.full_name
        clean_user = normalize_arabic(user_name)
        tokens = [t for t in clean_user.split() if len(t) >= 2]

        q_filter = Q()
        for t in tokens:
            q_filter |= Q(student_name_clean__icontains=t) | Q(student_name__icontains=t)

        candidates = []
        if tokens:
            records = (
                StudentMark.objects.filter(q_filter)
                .values('student_name_clean', 'student_name')
                .annotate(cnt=Count('id'))
                .order_by('-cnt')[:200]
            )

            seen_clean = set()
            for r in records:
                c_name = r['student_name_clean']
                if c_name in seen_clean:
                    continue
                seen_clean.add(c_name)

                sim = calculate_similarity(user_name, r['student_name'])
                if sim >= 35.0:
                    linked_ids = sorted(list(set(
                        StudentMark.objects.filter(student_name_clean=c_name)
                        .values_list('student_university_id', flat=True)
                    )))
                    primary_id = max(linked_ids, key=lambda x: (len(x), x)) if linked_ids else ""
                    candidates.append({
                        "student_university_id": primary_id,
                        "student_name": r['student_name'],
                        "all_student_ids": linked_ids,
                        "similarity_score": round(sim, 1),
                        "records_count": r['cnt']
                    })

            candidates.sort(key=lambda x: x['similarity_score'], reverse=True)

        return Response({
            "registered_name": user_name,
            "candidates": candidates[:15],
            "total_found": len(candidates)
        })


class ClaimIdentityView(APIView):
    """Binds chosen student ID to authenticated user."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        uni_id = request.data.get("student_university_id", "").strip()
        if not uni_id:
            return Response({"error": "student_university_id is required"}, status=400)
        request.user.linked_student_id = uni_id
        request.user.save()
        return Response({
            "message": f"تم ربط حسابك بالسجل الجامعي {uni_id} بنجاح.",
            "linked_student_id": uni_id
        })


class StudentSearchView(APIView):
    """Universal search supporting 2-part name, 3-part name, seat number with year-by-year formatting."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        raw_query = get_param(request, "query")
        name = get_param(request, "name") or raw_query
        student_id = get_param(request, "student_id")
        academic_year = get_param(request, "academic_year")
        course_name = get_param(request, "course_name")

        # 🚀 1. FAST INVERTED INDEX SEEK: Check precomputed StudentProfile records (<5ms)
        search_term = name or raw_query or student_id
        if search_term and not academic_year and not course_name:
            clean_term = normalize_arabic(search_term)
            toks = [t for t in clean_term.split() if len(t) >= 2]
            prof_q = Q()
            if search_term.isdigit():
                prof_q = Q(primary_id__icontains=search_term) | Q(all_student_ids__icontains=search_term)
            elif toks:
                for t in toks:
                    prof_q &= (Q(student_name_clean__icontains=t) | Q(student_name__icontains=t))

            profiles = StudentProfile.objects.filter(prof_q).order_by('-cumulative_gpa')[:25]
            if profiles.exists():
                out = []
                for p in profiles:
                    all_marks_flat = []
                    for y in p.years_summary:
                        all_marks_flat.extend(y.get('marks', []))
                    out.append({
                        "student_university_id": p.primary_id,
                        "student_name": p.student_name,
                        "all_student_ids": p.all_student_ids,
                        "academic_status": p.academic_status,
                        "academic_level": p.academic_level,
                        "department": p.department,
                        "cumulative_gpa": p.cumulative_gpa,
                        "passed_courses_count": p.passed_courses_count,
                        "carried_courses_count": p.carried_courses_count,
                        "unattempted_courses_count": p.unattempted_courses_count,
                        "total_courses_taken": p.total_courses_count,
                        "highest_mark_overall": p.highest_mark_overall,
                        "highest_mark_course": p.highest_mark_course,
                        "lowest_mark_overall": p.lowest_mark_overall,
                        "lowest_mark_course": p.lowest_mark_course,
                        "years_summary": p.years_summary,
                        "courses_inverted_map": p.courses_inverted_map,
                        "progress_chart": p.progress_chart,
                        "marks": all_marks_flat,
                        "marks_sample": all_marks_flat[:15]
                    })
                return Response(out)

        target_clean_names = []

        # If searching by seat number (or query is digits)
        search_id = student_id or (name if name.isdigit() else "")
        if search_id:
            s_marks = StudentMark.objects.filter(student_university_id=search_id)
            c_names = list(s_marks.values_list('student_name_clean', flat=True).distinct()[:25])
            for cn in c_names:
                if cn not in target_clean_names:
                    target_clean_names.append(cn)

        # If searching by name tokens (2-part or 3-part name)
        if name and not name.isdigit():
            clean = normalize_arabic(name)
            tokens = [tok for tok in clean.split() if len(tok) >= 2]
            if tokens:
                token_q = Q()
                for tok in tokens:
                    token_q &= (Q(student_name_clean__icontains=tok) | Q(student_name__icontains=tok))

                names_qs = (
                    StudentMark.objects.filter(token_q)
                    .values('student_name_clean')
                    .annotate(rec_cnt=Count('id'))
                    .order_by('-rec_cnt')
                    .values_list('student_name_clean', flat=True)[:60]
                )
                for cn in names_qs:
                    if cn not in target_clean_names:
                        target_clean_names.append(cn)

        # Fallback if only course or year was provided
        if not target_clean_names and (academic_year or course_name):
            qs = StudentMark.objects.all()
            if academic_year:
                qs = qs.filter(session__academic_year_str__icontains=academic_year)
            if course_name:
                qs = qs.filter(session__course__name__icontains=course_name)
            target_clean_names = list(qs.values_list('student_name_clean', flat=True).distinct()[:25])

        # Dynamic clustering: group name variants and permutations into unified student entities
        clusters = []
        for cn in target_clean_names:
            toks = clean_tokens(cn)
            f_toks = frozenset(toks)
            merged = False
            for group in clusters:
                for g_cn in group:
                    g_toks = clean_tokens(g_cn)
                    g_ftoks = frozenset(g_toks)
                    if len(f_toks) >= 3 and len(g_ftoks) >= 3 and f_toks == g_ftoks:
                        group.append(cn)
                        merged = True
                        break
                    if len(f_toks) >= 2 and len(g_ftoks) >= 2 and (f_toks.issubset(g_ftoks) or g_ftoks.issubset(f_toks)):
                        cn_seats = set(StudentMark.objects.filter(student_name_clean=cn).values_list('student_university_id', flat=True))
                        g_seats = set(StudentMark.objects.filter(student_name_clean=g_cn).values_list('student_university_id', flat=True))
                        if cn_seats.intersection(g_seats):
                            group.append(cn)
                            merged = True
                            break
                if merged:
                    break
            if not merged:
                clusters.append([cn])

        out = []
        for group in clusters:
            marks_qs = (
                StudentMark.objects.filter(student_name_clean__in=group)
                .select_related('session__course__academic_year')
                .order_by('session__academic_year_str', 'session__semester_num', 'id')
            )

            first_rec = marks_qs.first()
            if not first_rec:
                continue

            all_ids = sorted(list(set(marks_qs.values_list('student_university_id', flat=True))))
            primary_id = max(all_ids, key=lambda x: (len(x), x)) if all_ids else ""

            years_summary, cum_gpa, progress_chart = build_student_years_summary(marks_qs)

            total_unique_courses = sum(y['total_courses'] for y in years_summary)
            total_passed = sum(y['passed_count'] for y in years_summary)
            total_carried = sum(y['carried_count'] for y in years_summary)

            all_marks_flat = []
            for y in years_summary:
                all_marks_flat.extend(y['marks'])

            # Determine academic status
            carried_courses = [c for y in years_summary for c in y['carried_courses']]
            grace_candidates = [c for c in carried_courses if c.get('is_grace_eligible')]
            if total_carried == 0:
                academic_status = "ناجح ومرفع في كافة المقررات الدراسية"
            elif grace_candidates:
                if total_carried in [1, 2]:
                    academic_status = f"مؤهل للترفع التام واستكمال المقررات بموجب علامات المساعدة ({len(grace_candidates)} مواد مشمولة بالمرسوم)"
                else:
                    academic_status = f"مؤهل للترفع والنجاح بالنقل بموجب علامات المساعدة ({len(grace_candidates)} مواد مشمولة لخفض المحمول إلى 4)"
            elif total_carried <= 4:
                academic_status = f"طالب منقول للسنة التالية (يحمل {total_carried} مواد دراسية متبقية)"
            else:
                academic_status = f"طالب راسب في سنته (يحمل {total_carried} مواد دراسية متبقية)"

            all_unique_scores = []
            for y in years_summary:
                all_unique_scores.extend([p['final_score'] for p in y['passed_courses']])
                all_unique_scores.extend([c['last_score'] for c in y['carried_courses']])

            highest_score = max(all_unique_scores) if all_unique_scores else 0
            lowest_score = min(all_unique_scores) if all_unique_scores else 0
            highest_course = next((p["course_name"] for y in years_summary for p in y["passed_courses"] if p["final_score"] == highest_score), "")
            lowest_course = next((c["course_name"] for y in years_summary for c in y["carried_courses"] if c["last_score"] == lowest_score), "")
            if not lowest_course and all_unique_scores:
                lowest_course = next((p["course_name"] for y in years_summary for p in y["passed_courses"] if p["final_score"] == lowest_score), "")

            out.append({
                "student_university_id": primary_id,
                "student_name": format_student_name(first_rec.student_name),
                "all_student_ids": all_ids,
                "cumulative_gpa": cum_gpa,
                "academic_status": academic_status,
                "total_courses_taken": total_unique_courses,
                "passed_courses_count": total_passed,
                "carried_courses_count": total_carried,
                "highest_mark_overall": highest_score,
                "highest_mark_course": highest_course,
                "lowest_mark_overall": lowest_score,
                "lowest_mark_course": lowest_course,
                "total_records_count": marks_qs.count(),
                "years_summary": years_summary,
                "progress_chart": progress_chart,
                "marks": all_marks_flat,
                "marks_sample": all_marks_flat
            })

        return Response(out)


class StudentCareerSummaryView(APIView):
    """Academic Career Analytics: Full Year-by-Year Transcript, Attempts & Syrian Grace Marks Engine."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, student_id):
        student_id_str = unquote(str(student_id)).strip()
        name_param = get_param(request, "name")

        target_clean = ""
        student_name = ""

        # Step 1: Resolve the clean student name
        if name_param:
            target_clean = normalize_arabic(name_param)
        elif not student_id_str.isdigit():
            target_clean = normalize_arabic(student_id_str)
        else:
            # Numeric seat number
            if hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False) and getattr(request.user, 'full_name', ''):
                user_clean = normalize_arabic(request.user.full_name)
                tokens = [tok for tok in user_clean.split() if len(tok) >= 2]
                tok_q = Q(student_university_id=student_id_str)
                for tok in tokens:
                    tok_q &= Q(student_name_clean__icontains=tok)
                match = StudentMark.objects.filter(tok_q).first()
                if match:
                    target_clean = match.student_name_clean
                    student_name = match.student_name

        # 🚀 0. FAST INVERTED INDEX SEEK: Check precomputed StudentProfile records (<1ms)
        p_match = None
        if target_clean:
            p_match = StudentProfile.objects.filter(student_name_clean=target_clean).first()
            if not p_match:
                tokens = [tok for tok in target_clean.split() if len(tok) >= 2]
                if tokens:
                    t_q = Q()
                    for tok in tokens:
                        t_q &= (Q(student_name_clean__icontains=tok) | Q(student_name__icontains=tok))
                    p_match = StudentProfile.objects.filter(t_q).first()
        if not p_match and student_id_str:
            p_match = StudentProfile.objects.filter(primary_id=student_id_str).first()
        if not p_match and student_id_str:
            p_match = StudentProfile.objects.filter(all_student_ids__icontains=student_id_str).first()

        if p_match:
            all_passed = []
            all_carried = []
            all_unattempted = []
            all_marks_flat = []
            annual_gpas = {}
            for y in p_match.years_summary:
                all_passed.extend(y.get('passed_courses', []))
                all_carried.extend(y.get('carried_courses', []))
                all_unattempted.extend(y.get('unattempted_courses', []))
                all_marks_flat.extend(y.get('marks', []))
                annual_gpas[y['year_name']] = y.get('annual_gpa', 0.0)

            grace_eligible = []
            for g in [c for c in all_carried if c.get('is_grace_eligible')]:
                needed = g.get('required_grace_marks', 1)
                grace_eligible.append({
                    "course_name": g["course_name"],
                    "current_mark": g["last_score"],
                    "required_grace_marks": needed,
                    "status": g.get("status", "مشمولة بمساعدة الترفع"),
                    "explanation": g.get("grace_explanation", f"مادة مؤهلة لنيل {needed} علامة مساعدة بموجب مرسوم تنظيم الجامعات السورية.")
                })

            return Response({
                "student_university_id": p_match.primary_id,
                "student_name": p_match.student_name,
                "all_student_ids": p_match.all_student_ids,
                "academic_status": p_match.academic_status,
                "academic_level": p_match.academic_level,
                "department": p_match.department,
                "cumulative_gpa": p_match.cumulative_gpa,
                "passed_courses_count": p_match.passed_courses_count,
                "carried_courses_count": p_match.carried_courses_count,
                "unattempted_courses_count": p_match.unattempted_courses_count,
                "total_courses_count": p_match.total_courses_count,
                "total_courses_taken": p_match.total_courses_count,
                "highest_mark_overall": p_match.highest_mark_overall,
                "highest_mark_course": p_match.highest_mark_course,
                "lowest_mark_overall": p_match.lowest_mark_overall,
                "lowest_mark_course": p_match.lowest_mark_course,
                "years_summary": p_match.years_summary,
                "courses_inverted_map": p_match.courses_inverted_map,
                "progress_chart": p_match.progress_chart,
                "passed_courses": all_passed,
                "carried_courses": all_carried,
                "unattempted_courses": all_unattempted,
                "carried_subjects": [c["course_name"] for c in all_carried],
                "remaining_subjects_count": len(all_carried),
                "grace_marks_eligible": grace_eligible,
                "annual_gpas": annual_gpas,
                "marks": all_marks_flat,
                "total_attempts_history_count": len(all_marks_flat)
            })

        if target_clean:
            tokens = [tok for tok in target_clean.split() if len(tok) >= 2]
            tok_q = Q()
            for tok in tokens:
                tok_q &= (Q(student_name_clean__icontains=tok) | Q(student_name__icontains=tok))

            marks = (
                StudentMark.objects
                .select_related('session__course__academic_year')
                .filter(tok_q)
                .order_by('session__academic_year_str', 'session__semester_num', 'id')
            )
        else:
            marks = (
                StudentMark.objects
                .select_related('session__course__academic_year')
                .filter(student_university_id=student_id_str)
                .order_by('session__academic_year_str', 'session__semester_num', 'id')
            )

        if not marks.exists():
            return Response({"error": "لا توجد سجلات لهذا الطالب"}, status=404)

        if not student_name:
            student_name = marks.first().student_name

        all_linked_ids = sorted(list(set(marks.values_list('student_university_id', flat=True))))
        primary_id = max(all_linked_ids, key=lambda x: (len(x), x)) if all_linked_ids else student_id_str

        # Build year-by-year summary
        years_summary, cum_gpa, progress_chart = build_student_years_summary(marks)

        # Flatten passed and carried lists across all years
        all_passed_courses = []
        all_carried_courses = []
        all_unique_scores = []
        annual_gpas = {}

        for y in years_summary:
            all_passed_courses.extend(y['passed_courses'])
            all_carried_courses.extend(y['carried_courses'])
            annual_gpas[y['year_name']] = y['annual_gpa']
            all_unique_scores.extend([p['final_score'] for p in y['passed_courses']])
            all_unique_scores.extend([c['last_score'] for c in y['carried_courses']])

        all_passed_courses.sort(key=lambda x: x['final_score'], reverse=True)
        all_carried_courses.sort(key=lambda x: x['last_score'], reverse=True)

        # Syrian Grace Marks Evaluator
        grace_eligible = []
        grace_candidates = [c for c in all_carried_courses if c["is_grace_eligible"]]

        for g in grace_candidates:
            needed = g.get("required_grace_marks", 1)
            grace_eligible.append({
                "course_name": g["course_name"],
                "current_mark": g["last_score"],
                "required_grace_marks": needed,
                "status": g.get("status", "مشمولة بمساعدة الترفع"),
                "explanation": g.get("grace_explanation", f"مادة مؤهلة لنيل {needed} علامة مساعدة بموجب مرسوم تنظيم الجامعات السورية.")
            })

        highest_score = max(all_unique_scores) if all_unique_scores else 0
        lowest_score = min(all_unique_scores) if all_unique_scores else 0
        highest_course = next((p["course_name"] for p in all_passed_courses if p["final_score"] == highest_score), "")
        lowest_course = next((c["course_name"] for c in all_carried_courses if c["last_score"] == lowest_score), "")
        if not lowest_course and all_passed_courses:
            lowest_course = min(all_passed_courses, key=lambda x: x["final_score"])["course_name"]

        total_carried = len(all_carried_courses)
        if total_carried == 0:
            academic_status = "ناجح ومرفع في كافة المقررات الدراسية"
        elif grace_candidates:
            if total_carried in [1, 2]:
                academic_status = f"مؤهل للترفع التام واستكمال المقررات بموجب علامات المساعدة ({len(grace_candidates)} مواد مشمولة بالمرسوم)"
            else:
                academic_status = f"مؤهل للترفع والنجاح بالنقل بموجب علامات المساعدة ({len(grace_candidates)} مواد مشمولة لخفض المحمول إلى 4)"
        elif total_carried <= 4:
            academic_status = f"طالب منقول للسنة التالية (يحمل {total_carried} مواد دراسية متبقية)"
        else:
            academic_status = f"طالب راسب في سنته (يحمل {total_carried} مواد دراسية متبقية)"

        return Response({
            "student_university_id": primary_id,
            "student_name": student_name,
            "all_student_ids": all_linked_ids,
            "cumulative_gpa": cum_gpa,
            "academic_status": academic_status,
            "passed_courses_count": len(all_passed_courses),
            "carried_courses_count": len(all_carried_courses),
            "total_courses_count": len(all_passed_courses) + len(all_carried_courses),
            "passed_courses": all_passed_courses,
            "carried_courses": all_carried_courses,
            "carried_subjects": [c["course_name"] for c in all_carried_courses],
            "remaining_subjects_count": len(all_carried_courses),
            "grace_marks_eligible": grace_eligible,
            "highest_mark_overall": highest_score,
            "highest_mark_course": highest_course,
            "lowest_mark_overall": lowest_score,
            "lowest_mark_course": lowest_course,
            "annual_gpas": annual_gpas,
            "years_summary": years_summary,
            "progress_chart": progress_chart,
            "total_attempts_history_count": marks.count()
        })


ADVANCED_BEYOND_CACHE = {}
LEADERBOARD_CACHE = {}
COURSE_TOPPERS_CACHE = {}


def get_advanced_beyond(yr):
    if yr in ADVANCED_BEYOND_CACHE:
        return ADVANCED_BEYOND_CACHE[yr]
    
    higher_names = set()
    current_years = ['2024-2025', '2025-2026']
    for higher_yr in range(yr + 1, 6):
        # Anyone with seat starting with higher year (5-digit seats only)
        seats_names = StudentMark.objects.filter(
            Q(session__academic_year_str__in=current_years) | Q(session__session_title__startswith='2025'),
            student_university_id__regex=rf'^{higher_yr}\d{{4}}$'
        ).values_list('student_name_clean', flat=True)
        higher_names.update(seats_names)
        
        # Anyone with mark in higher year course
        course_names = StudentMark.objects.filter(
            session__course__academic_year_id=higher_yr
        ).values_list('student_name_clean', flat=True)
        higher_names.update(course_names)

    # Anyone who already attempted courses in THIS year in prior exam sessions (before 2025)
    # This guarantees ONLY new regular students of this year (الطلاب الجدد لهذا العام) appear on the honor board!
    prior_year_attempts = StudentMark.objects.filter(
        session__course__academic_year_id=yr
    ).exclude(
        session__session_title__startswith='2025'
    ).values_list('student_name_clean', flat=True)
    higher_names.update(prior_year_attempts)

    # For Year 2: Anyone who carried or took Year 1 courses in 2025 with a Year 2 seat
    if yr == 2:
        y1_carried = StudentMark.objects.filter(
            session__course__academic_year_id=1,
            session__session_title__startswith='2025',
            student_university_id__regex=r'^2\d{4}$'
        ).values_list('student_name_clean', flat=True)
        higher_names.update(y1_carried)

    # For Year 3: Anyone who carried Year 1 or 2 courses in 2025 with a Year 3 seat
    if yr == 3:
        lower_carried = StudentMark.objects.filter(
            session__course__academic_year_id__in=[1, 2],
            session__session_title__startswith='2025',
            student_university_id__regex=r'^3\d{4}$'
        ).values_list('student_name_clean', flat=True)
        higher_names.update(lower_carried)

    # Add normalized variations (with/without space for عبد/ابو/ال)
    expanded = set(higher_names)
    for n in higher_names:
        if 'عبد' in n:
            expanded.add(n.replace('عبد', 'عبد '))
            expanded.add(n.replace('عبد ', 'عبد'))
        if 'ابو' in n:
            expanded.add(n.replace('ابو', 'ابو '))
            expanded.add(n.replace('ابو ', 'ابو'))
    ADVANCED_BEYOND_CACHE[yr] = expanded
    return expanded


class Top30LeaderboardView(APIView):
    """Top 50 Passing students per academic year, strictly segregated by current 2025 session and department."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        year_id_param = get_param(request, "year_id")
        dept_id_param = get_param(request, "department_id")

        target_years = [int(year_id_param)] if year_id_param and year_id_param.isdigit() else list(range(1, 6))

        years_results = {}
        top_list = []

        for yr in target_years:
            dept_id = int(dept_id_param) if dept_id_param and dept_id_param.isdigit() else 2
            cache_key = (yr, dept_id)
            if cache_key in LEADERBOARD_CACHE:
                years_results[yr] = LEADERBOARD_CACHE[cache_key]
                top_list.extend(years_results[yr])
                continue

            yr_name = ARABIC_YEAR_NAMES.get(yr, f'السنة {yr}')

            dept_label = "كلية الهندسة المعلوماتية"

            if yr == 1:
                seat_regex = r'^(1\d{4}|26\d{5})$'
                min_c = 10
            elif yr == 2:
                seat_regex = r'^2\d{4}$'
                min_c = 11
            elif yr == 3:
                seat_regex = r'^3\d{4}$'
                min_c = 10
            elif yr == 5:
                # Department code mapping: 1 = Networks, 2 = Software, 3 = AI (handle 4 as 3 for legacy)
                if dept_id in [3, 4]:
                    d_code = '3'
                    dept_label = "الذكاء الصنعي"
                    min_c = 9  # Year 5 AI curriculum is strictly 9 courses
                elif dept_id in [1]:
                    d_code = '1'
                    dept_label = "شبكات الحاسوب"
                    min_c = 8  # Year 5 Networks curriculum is 8-9 courses
                else:
                    d_code = '2'
                    dept_label = "هندسة البرمجيات ونظم المعلومات"
                    min_c = 9  # Year 5 Software curriculum is strictly 9 courses
                seat_regex = rf'^{yr}{d_code}\d{{3}}$'
            elif yr == 4:
                if dept_id in [3, 4]:
                    d_code = '3'
                    dept_label = "الذكاء الصنعي"
                    min_c = 12
                elif dept_id in [1]:
                    d_code = '1'
                    dept_label = "شبكات الحاسوب"
                    min_c = 10
                else:
                    d_code = '2'
                    dept_label = "هندسة البرمجيات ونظم المعلومات"
                    min_c = 12
                seat_regex = rf'^{yr}{d_code}\d{{3}}$'

            base_qs = (
                StudentMark.objects.filter(
                    student_university_id__regex=seat_regex,
                    session__course__academic_year_id=yr,
                    session__session_title__startswith='2025',
                    total_mark__gte=60.0
                )
                .exclude(student_name_clean__in=get_advanced_beyond(yr))
            )

            cands = (
                base_qs
                .values('student_name_clean')
                .annotate(
                    passed_cnt=Count('session__course_id', distinct=True),
                    student_name=Max('student_name')
                )
                .filter(passed_cnt__gte=min_c)
            )

            clean_names = [c['student_name_clean'] for c in cands]

            # Find any student who has an unresolved failed course in this academic year
            failed_filter = StudentMark.objects.filter(
                session__course__academic_year_id=yr,
                session__session_title__startswith='2025',
                student_name_clean__in=clean_names
            )

            failed_courses = (
                failed_filter
                .values('student_name_clean', 'session__course_id')
                .annotate(best=Max('total_mark'))
                .filter(best__lt=60.0)
            )
            has_failed_names = set(f['student_name_clean'] for f in failed_courses)

            # Fetch all candidate marks in ONE single query
            cand_marks_qs = StudentMark.objects.filter(
                session__course__academic_year_id=yr,
                session__session_title__startswith='2025',
                student_name_clean__in=clean_names
            ).values('student_name_clean', 'session__course_id', 'total_mark', 'student_university_id', 'student_name')

            best_marks_map = defaultdict(lambda: defaultdict(float))
            student_sid_map = {}
            student_display_names = {}
            for row in cand_marks_qs:
                c_name = row['student_name_clean']
                cid = row['session__course_id']
                m = row['total_mark']
                if m > best_marks_map[c_name][cid]:
                    best_marks_map[c_name][cid] = m
                sid = row['student_university_id']
                if sid:
                    curr = student_sid_map.get(c_name, "")
                    if not curr:
                        student_sid_map[c_name] = sid
                    elif len(curr) != 5 and len(sid) == 5:
                        student_sid_map[c_name] = sid
                if c_name not in student_display_names and row.get('student_name'):
                    student_display_names[c_name] = row['student_name']

            evaluated_students = []
            for c in cands:
                cn = c['student_name_clean']
                if cn in has_failed_names:
                    continue  # MUST be passing with no carried courses!

                raw_name = student_display_names.get(cn, c.get('student_name', ''))
                name = format_student_name(raw_name)
                c_dict = best_marks_map.get(cn, {})
                if not c_dict or len(c_dict) < min_c:
                    continue
                exact_avg = sum(c_dict.values()) / len(c_dict)
                sid = student_sid_map.get(cn, "")

                evaluated_students.append({
                    "student_university_id": sid,
                    "student_name": name,
                    "passed_courses_count": len(c_dict),
                    "average_mark": round(exact_avg, 2),
                    "academic_year": yr_name,
                    "academic_year_id": yr,
                    "department": dept_label,
                    "status": "مرفع وناجح في كافة المقررات"
                })

            # Sort primarily by passed_courses_count descending, then by average_mark descending!
            evaluated_students.sort(key=lambda x: (x['passed_courses_count'], x['average_mark']), reverse=True)

            yr_toppers = []
            for idx, item in enumerate(evaluated_students[:50]):
                item['rank'] = idx + 1
                yr_toppers.append(item)
                top_list.append(item)

            LEADERBOARD_CACHE[cache_key] = yr_toppers
            years_results[yr] = yr_toppers

        # If a specific year was requested, return that year's top 50
        if year_id_param and year_id_param.isdigit():
            return Response(years_results.get(int(year_id_param), []))

        return Response({
            "top_students": top_list,
            "years_top20": years_results,
            "years_top50": years_results
        })


# Course lists accurately extracted from the Marks/ directory hierarchy
CURRICULUM_COURSES = {
    1: [
        'البرمجة 1', 'البرمجة 2', 'التحليل 1', 'التحليل 2', 'الثقافة القومية الاشتراكية',
        'الجبر الخطي', 'الجبر العام', 'الدارات الكهربائية و الالكترونية', 'الفيزياء',
        'اللغة العربية', 'انكليزي 1', 'انكليزي 2', 'مبادئ عمل الحواسيب'
    ],
    2: [
        'الاتصالات الرقمية', 'الاحتمالات و الاحصاء', 'البرمجة 3', 'التحليل 3',
        'التحليل العددي', 'الخوارزميات و بنى المعطيات 1', 'الخوارزميات و بنى المعطيات 2',
        'الدارات المنطقية', 'انكليزي 3', 'انكليزي 4', 'بنيان الحواسيب 1', 'مهارات التواصل'
    ],
    3: [
        'أساسيات الشبكات', 'البيانيات', 'الحسابات العلمية', 'اللغات الصورية',
        'بحوث العمليات', 'بنيان الحواسيب 2', 'قواعد المعطيات 1', 'لغات البرمجة',
        'مبادئ الذكاء الصنعي', 'مشروع 1'
    ],
    4: {
        2: [  # Software
            'الاقتصاد و الإدارة في مؤسسة', 'البرمجة التفرعية', 'التسويق', 'المترجمات',
            'خوارزميات البحث الذكية', 'قواعد المعطيات 2', 'مشروع 2', 'مشروع المترجمات',
            'نظم الوسائط المتعددة', 'نظم تشغيل 1', 'هندسة البرمجيات 1', 'هندسة البرمجيات 2'
        ],
        3: [  # AI
            'الاقتصاد و الإدارة في مؤسسة', 'البرمجة التفرعية', 'التسويق', 'الحقائق الافتراضية',
            'الشبكات العصبونية', 'المترجمات', 'خوارزميات البحث الذكية', 'مشروع 2',
            'نظم الوسائط المتعددة', 'نظم تشغيل 1', 'نظم قواعد المعرفة', 'هندسة البرمجيات 1'
        ],
        1: [  # Networks
            'الاقتصاد و الإدارة في مؤسسة', 'البرمجة التفرعية', 'التسويق', 'الشبكات العصبونية',
            'برتوكولات الاتصالات الحاسوبية', 'برمجة التطبيقات الشبكية', 'خوارزميات البحث الذكية',
            'مشروع 2', 'نظم التشغيل 2', 'نظم الوسائط المتعددة', 'نظم تشغيل 1', 'هندسة البرمجيات 1'
        ]
    },
    5: {
        2: [  # Software
            'أمن نظم معلومات', 'إدارة المشاريع', 'النظم و التطبيقات الموزعة', 'تطبيقات الانترنت',
            'قواعد المعطيات المتقدمة', 'مشروع تخرج', 'نظم البحث عن المعلومات', 'هندسة البرمجيات 3', 'هندسة نظم المعلومات'
        ],
        3: [  # AI
            'أمن الشبكات الحاسوبية', 'أمن نظم معلومات', 'إدارة المشاريع', 'استكشاف المعرفة',
            'التعلم التلقائي', 'الرؤيا الحاسوبية', 'الروبوتية', 'المنطق الترجيحي و الخوارزميات الوراثية',
            'مشروع تخرج', 'معالجة اللغات الطبيعية', 'نظم البحث عن المعلومات'
        ],
        1: [  # Networks
            'أمن الشبكات الحاسوبية', 'أمن نظم معلومات', 'إدارة الشبكات الحاسوبية', 'إدارة المشاريع',
            'النظم و التطبيقات الموزعة', 'تصميم الشبكات الحاسوبية', 'مشروع تخرج', 'نظم الزمن الحقيقي',
            'نمذجة و محاكاة النظم الشبكية'
        ]
    }
}


class CourseToppersView(APIView):
    """Top 3 Toppers for every course from its latest official exam session (2025/2026)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        year_id = get_param(request, "year_id")
        dept_id = get_param(request, "department_id")

        yr = int(year_id) if year_id and year_id.isdigit() else 1
        d_id = int(dept_id) if dept_id and dept_id.isdigit() else 2
        if d_id == 4:
            d_id = 3  # Normalize AI department code 4 to 3

        cache_key = (yr, d_id)
        if cache_key in COURSE_TOPPERS_CACHE:
            return Response(COURSE_TOPPERS_CACHE[cache_key])

        # Get course names list for this year and department
        if yr in [1, 2, 3]:
            course_names = CURRICULUM_COURSES.get(yr, [])
            prefix = str(yr)
        else:
            dept_map = CURRICULUM_COURSES.get(yr, {})
            course_names = dept_map.get(d_id, dept_map.get(2, []))
            d_code = '3' if d_id in [3, 4] else ('1' if d_id == 1 else '2')
            prefix = f"{yr}{d_code}"

        out = []
        for cname in course_names:
            c = Course.objects.filter(name=cname, academic_year_id=yr).first()
            if not c:
                c = Course.objects.filter(name=cname).first()

            # Priority 1: 2025 exam session with department/year prefix
            marks_qs = (
                StudentMark.objects.filter(
                    session__course__name=cname,
                    session__session_title__startswith='2025',
                    student_university_id__startswith=prefix,
                    total_mark__gt=0
                )
                .order_by('-total_mark', '-id')
            )

            # Fallback 1: 2025 exam session without prefix constraint (e.g. shared courses)
            if not marks_qs.exists():
                marks_qs = (
                    StudentMark.objects.filter(
                        session__course__name=cname,
                        session__session_title__startswith='2025',
                        total_mark__gt=0
                    )
                    .order_by('-total_mark', '-id')
                )

            # Fallback 2: Any 2024-2026 session with prefix
            if not marks_qs.exists():
                marks_qs = (
                    StudentMark.objects.filter(
                        session__course__name=cname,
                        session__academic_year_str__in=['2024-2025', '2025-2026'],
                        student_university_id__startswith=prefix,
                        total_mark__gt=0
                    )
                    .order_by('-total_mark', '-id')
                )

            # Fallback 3: Any 2024-2026 session without prefix
            if not marks_qs.exists():
                marks_qs = (
                    StudentMark.objects.filter(
                        session__course__name=cname,
                        session__academic_year_str__in=['2024-2025', '2025-2026'],
                        total_mark__gt=0
                    )
                    .order_by('-total_mark', '-id')
                )

            # Fallback 4: Latest exam session in history
            if not marks_qs.exists() and c:
                sessions = list(ExamSession.objects.filter(course=c, marks__total_mark__gt=0).distinct())
                if sessions:
                    def session_sort_key(s):
                        m = re.search(r'(20\d\d)', s.session_title)
                        y_num = int(m.group(1)) if m else 0
                        return (y_num, s.semester_num or 0, s.id)
                    sessions.sort(key=session_sort_key, reverse=True)
                    latest_sess = sessions[0]
                    marks_qs = StudentMark.objects.filter(session=latest_sess, total_mark__gt=0).order_by('-total_mark')

            top_5 = []
            seen = set()
            display_session = ""
            display_year = "2024-2025"

            for m in marks_qs:
                clean = m.student_name_clean
                if clean in seen:
                    continue
                seen.add(clean)

                if not display_session and m.session:
                    display_session = m.session.session_title
                    display_year = m.session.academic_year_str

                top_5.append({
                    "rank": len(top_5) + 1,
                    "student_name": format_student_name(m.student_name),
                    "student_id": m.student_university_id,
                    "mark": m.total_mark
                })
                if len(top_5) == 5:
                    break

            if top_5:
                out.append({
                    "course_id": c.id if c else 0,
                    "course_name": cname,
                    "academic_year": display_year,
                    "session_title": display_session,
                    "top_students": top_5,
                    "top_student_name": top_5[0]["student_name"],
                    "top_student_id": top_5[0]["student_id"],
                    "highest_mark": top_5[0]["mark"]
                })

        COURSE_TOPPERS_CACHE[cache_key] = out
        return Response(out)


class SingleMarkPDFView(APIView):
    """Download single course mark as PDF."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, mark_id):
        try:
            m = StudentMark.objects.select_related('session__course').get(id=mark_id)
        except StudentMark.DoesNotExist:
            return Response({"error": "العلامة غير موجودة"}, status=404)

        data = {
            "student_name": m.student_name,
            "student_university_id": m.student_university_id,
            "course_name": m.session.course.name,
            "session_title": m.session.session_title,
            "practical_mark": m.practical_mark,
            "theoretical_mark": m.theoretical_mark,
            "total_mark": m.total_mark,
            "result_status": m.result_status
        }
        buf = generate_mark_pdf(data)
        response = HttpResponse(buf.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename=mark_{mark_id}.pdf'
        return response


class CareerTranscriptPDFView(APIView):
    """Download full academic career transcript PDF with year-by-year formatting."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, student_id):
        summary_view = StudentCareerSummaryView()
        res = summary_view.get(request, student_id)
        if res.status_code != 200:
            return res
        buf = generate_transcript_pdf(res.data)
        response = HttpResponse(buf.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename=transcript_{student_id}.pdf'
        return response


class GDriveSyncTriggerView(APIView):
    """Checks and syncs Google Drive folder."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        res = sync_google_drive()
        return Response(res)


# ==========================================
# Lectures API Views
# ==========================================

class LecturesSyncView(APIView):
    """Sync lectures from Google Drive folder into the database."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        result = sync_lectures_from_drive()
        return Response(result)


class LecturesTreeView(APIView):
    """Get the full lectures tree (academic years -> study years -> subjects -> files)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        year_label = get_param(request, "year")
        study_year = get_param(request, "study_year")
        study_year_num = int(study_year) if study_year.isdigit() else None
        tree = get_lectures_tree(year_label=year_label or None, study_year_num=study_year_num)
        return Response({"years": tree, "total_academic_years": len(tree)})


class LectureAcademicYearsView(APIView):
    """List all available academic years for lectures."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        years = LectureAcademicYear.objects.all().order_by('-year_label').values(
            'year_label', 'drive_folder_url', 'drive_folder_id'
        )
        return Response({"academic_years": list(years)})


class LectureSubjectsView(APIView):
    """List subjects for a given academic year + study year."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        year_label = get_param(request, "year")
        study_year_num = get_param(request, "study_year")

        qs = LectureSubject.objects.select_related('study_year__academic_year')
        if year_label:
            qs = qs.filter(study_year__academic_year__year_label=year_label)
        if study_year_num.isdigit():
            qs = qs.filter(study_year__year_number=int(study_year_num))

        result = []
        for subj in qs:
            result.append({
                "id": subj.id,
                "subject_name": subj.subject_name,
                "drive_folder_url": subj.drive_folder_url,
                "lecture_count": subj.lectures.count(),
                "study_year": subj.study_year.year_number,
                "year_name": subj.study_year.year_name,
            })
        return Response({"subjects": result})


class LectureFilesView(APIView):
    """Get all lecture files, optionally filtered by subject/year."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        subject_id = get_param(request, "subject_id")
        subject_name = get_param(request, "subject_name")
        year_label = get_param(request, "year")
        study_year_num = get_param(request, "study_year")
        search = get_param(request, "search")

        qs = Lecture.objects.select_related('subject__study_year__academic_year')

        if subject_id.isdigit():
            qs = qs.filter(subject_id=int(subject_id))
        elif subject_name:
            qs = qs.filter(subject__subject_name__iexact=subject_name)

        if year_label:
            qs = qs.filter(subject__study_year__academic_year__year_label=year_label)
        if study_year_num.isdigit():
            qs = qs.filter(subject__study_year__year_number=int(study_year_num))
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(subject__subject_name__icontains=search)
            )

        result = [
            {
                "id": lec.id,
                "title": lec.title,
                "file_type": lec.file_type,
                "drive_view_url": lec.drive_view_url,
                "drive_download_url": lec.drive_download_url,
                "date_uploaded": lec.date_uploaded,
                "subject_name": lec.subject.subject_name,
                "study_year": lec.subject.study_year.year_number,
                "year_name": lec.subject.study_year.year_name,
                "academic_year": lec.subject.study_year.academic_year.year_label,
            }
            for lec in qs[:300]
        ]
        return Response({"lectures": result, "total": qs.count()})
