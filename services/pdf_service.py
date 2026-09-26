import io
import os
import datetime
import arabic_reshaper
from bidi.algorithm import get_display

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, Image, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from pathlib import Path
from matplotlib import font_manager
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register Arabic-capable TrueType Fonts from bundled project folder or system
BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_FONT_REGULAR = BASE_DIR / "fonts" / "arial.ttf"
LOCAL_FONT_BOLD = BASE_DIR / "fonts" / "arialbd.ttf"

FONT_NAME = "ArabicArial"
BOLD_FONT = "ArabicArialBold"

def init_fonts():
    global FONT_NAME, BOLD_FONT
    try:
        if LOCAL_FONT_REGULAR.exists() and LOCAL_FONT_BOLD.exists():
            pdfmetrics.registerFont(TTFont("ArabicArial", str(LOCAL_FONT_REGULAR)))
            pdfmetrics.registerFont(TTFont("ArabicArialBold", str(LOCAL_FONT_BOLD)))
            font_manager.fontManager.addfont(str(LOCAL_FONT_REGULAR))
            font_manager.fontManager.addfont(str(LOCAL_FONT_BOLD))
            plt.rcParams['font.family'] = font_manager.FontProperties(fname=str(LOCAL_FONT_REGULAR)).get_name()
            return
        elif os.path.exists("C:/Windows/Fonts/arial.ttf"):
            pdfmetrics.registerFont(TTFont("ArabicArial", "C:/Windows/Fonts/arial.ttf"))
            pdfmetrics.registerFont(TTFont("ArabicArialBold", "C:/Windows/Fonts/arialbd.ttf"))
            plt.rcParams['font.family'] = 'Arial'
            return
        elif os.path.exists("C:/Windows/Fonts/tahoma.ttf"):
            pdfmetrics.registerFont(TTFont("ArabicArial", "C:/Windows/Fonts/tahoma.ttf"))
            pdfmetrics.registerFont(TTFont("ArabicArialBold", "C:/Windows/Fonts/tahomabd.ttf"))
            plt.rcParams['font.family'] = 'Tahoma'
            return
        else:
            linux_fonts = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
            ]
            for lf in linux_fonts:
                if os.path.exists(lf):
                    pdfmetrics.registerFont(TTFont("ArabicArial", lf))
                    pdfmetrics.registerFont(TTFont("ArabicArialBold", lf))
                    return
            FONT_NAME = "Helvetica"
            BOLD_FONT = "Helvetica-Bold"
    except Exception as e:
        print("Font registration notice:", e)

init_fonts()

reshaper = arabic_reshaper.ArabicReshaper({
    'delete_harakat': True,
    'support_ligatures': True,
    'support_zwj': True,
})

def ar(text) -> str:
    """Reshape Arabic text for RTL display in ReportLab."""
    if not text:
        return ""
    try:
        s = str(text)
        has_arabic = any('\u0600' <= c <= '\u06ff' or '\ufe70' <= c <= '\ufeff' for c in s)
        if not has_arabic:
            return s
        reshaped = reshaper.reshape(s)
        return get_display(reshaped, base_dir='R')
    except Exception:
        return str(text)


class NumberedCanvas(canvas.Canvas):
    """Custom canvas that adds running header/footer with total page count."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        page_num = self._pageNumber
        width = 595.27
        height = 841.89

        # Draw running header on page 2+
        if page_num > 1:
            self.setFont(FONT_NAME, 8)
            self.setFillColor(colors.HexColor('#64748B'))
            header_right = ar("الجمهورية العربية السورية - جامعة دمشق | كلية الهندسة المعلوماتية")
            header_left = ar("كشف المسيرة الأكاديمية الرسمي")
            self.drawString(28, height - 20, header_left)
            self.drawRightString(width - 28, height - 20, header_right)
            self.setStrokeColor(colors.HexColor('#CBD5E1'))
            self.setLineWidth(0.5)
            self.line(28, height - 23, width - 28, height - 23)

        # Draw running footer on ALL pages
        self.setStrokeColor(colors.HexColor('#E2E8F0'))
        self.setLineWidth(0.75)
        self.line(28, 25, width - 28, 25)

        self.setFont(FONT_NAME, 7.5)
        self.setFillColor(colors.HexColor('#64748B'))
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        footer_right = f"{ar('تاريخ الطباعة والاعتماد:')} {now_str}"
        footer_left = f"{ar('صفحة')} {page_num} {ar('من')} {total_pages}"

        self.drawString(28, 15, footer_left)
        self.drawRightString(width - 28, 15, footer_right)

        self.restoreState()


def generate_career_charts(career_data: dict) -> io.BytesIO:
    """Generates dual high-resolution charts for the student career."""
    years_summary = career_data.get("years_summary", [])
    passed_courses = career_data.get("passed_courses", [])
    carried_courses = career_data.get("carried_courses", [])
    all_courses = passed_courses + carried_courses

    plt.rcParams['font.family'] = 'Arial'

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.4, 3.4), dpi=190)
    fig.patch.set_facecolor('#ffffff')

    # Chart 1: Annual GPA Progression
    yr_labels = []
    yr_gpas = []
    for y in years_summary:
        raw_name = y.get("year_name", "")
        if "أولى" in raw_name:
            short_name = "السنة الأولى"
        elif "ثانية" in raw_name:
            short_name = "السنة الثانية"
        elif "ثالثة" in raw_name:
            short_name = "السنة الثالثة"
        elif "رابعة" in raw_name:
            short_name = "السنة الرابعة"
        elif "خامسة" in raw_name:
            short_name = "السنة الخامسة"
        else:
            short_name = raw_name[:15]
        yr_labels.append(short_name)
        yr_gpas.append(float(y.get("annual_gpa", 0.0)))

    if not yr_labels:
        yr_labels = ["المسيرة"]
        yr_gpas = [float(career_data.get("cumulative_gpa", 0.0))]

    bar_colors = ['#1E3A8A', '#2563EB', '#3B82F6', '#4F46E5', '#059669'][:len(yr_labels)]
    bars = ax1.bar(yr_labels, yr_gpas, color=bar_colors, width=0.52, edgecolor='#0F172A', linewidth=0.7)

    ax1.axhline(60, color='#DC2626', linestyle='--', linewidth=1, alpha=0.75, label='حد النجاح 60%')
    ax1.axhline(80, color='#059669', linestyle=':', linewidth=1.1, alpha=0.85, label='عتبة الامتياز 80%')
    
    min_val = min(yr_gpas) if yr_gpas else 50
    ax1.set_ylim(max(0, min(40, int(min_val - 10))), 105)
    ax1.set_title('مخطط تطور المعدل السنوي (GPA)', fontdict={'fontsize': 10.5, 'fontweight': 'bold', 'color': '#0F172A'}, pad=8)
    ax1.grid(axis='y', linestyle=':', alpha=0.45)
    ax1.legend(loc='lower right', fontsize=7.2, framealpha=0.85)

    for bar in bars:
        yval = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2.0, yval + 1.2, f'{yval:.1f}%',
                 ha='center', va='bottom', fontsize=8, fontweight='bold', color='#0F172A')

    # Chart 2: Grade Distribution Donut Chart
    grades_count = {
        'excellent': 0,    # >= 85
        'very_good': 0,    # 75 - 84
        'good': 0,         # 65 - 74
        'acceptable': 0,   # 60 - 64
        'failed': 0        # < 60
    }
    for c in passed_courses:
        score = c.get('final_score', 0)
        if score >= 85:
            grades_count['excellent'] += 1
        elif score >= 75:
            grades_count['very_good'] += 1
        elif score >= 65:
            grades_count['good'] += 1
        else:
            grades_count['acceptable'] += 1

    for c in carried_courses:
        grades_count['failed'] += 1

    labels = []
    sizes = []
    colors_list = []

    palette = [
        ('excellent', 'ممتاز (>=85)', '#059669'),
        ('very_good', 'جيد جداً (75-84)', '#2563EB'),
        ('good', 'جيد (65-74)', '#6366F1'),
        ('acceptable', 'مقبول (60-64)', '#D97706'),
        ('failed', 'راسب (<60)', '#DC2626')
    ]

    for key, label, col in palette:
        cnt = grades_count[key]
        if cnt > 0:
            labels.append(f"{label} [{cnt}]")
            sizes.append(cnt)
            colors_list.append(col)

    if not sizes:
        sizes = [1]
        labels = ["لا توجد مقررات"]
        colors_list = ['#CBD5E1']

    wedges, texts, autotexts = ax2.pie(
        sizes,
        labels=labels,
        autopct='%1.0f%%',
        startangle=140,
        colors=colors_list,
        textprops={'fontsize': 7.2, 'color': '#0F172A'},
        pctdistance=0.76,
        wedgeprops=dict(width=0.45, edgecolor='white', linewidth=1.2)
    )
    for autotext in autotexts:
        autotext.set_fontsize(7.2)
        autotext.set_fontweight('bold')
        autotext.set_color('white')

    ax2.set_title('توزيع تقديرات المقررات الدراسية', fontdict={'fontsize': 10.5, 'fontweight': 'bold', 'color': '#0F172A'}, pad=8)
    
    total_cnt = len(all_courses)
    ax2.text(0, 0.06, f"{total_cnt}", ha='center', va='center', fontsize=12, fontweight='bold', color='#1E3A8A')
    ax2.text(0, -0.14, "مقرراً", ha='center', va='center', fontsize=7.5, color='#64748B')

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=190, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_transcript_pdf(career_data: dict) -> io.BytesIO:
    """Generates world-class comprehensive transcript PDF with charts and official branding."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=26,
        leftMargin=26,
        topMargin=26,
        bottomMargin=34
    )
    story = []
    styles = getSampleStyleSheet()

    # Custom styles
    title_bold = ParagraphStyle('TitleBold', parent=styles['Heading1'], fontName=BOLD_FONT, fontSize=12, leading=15, alignment=1, textColor=colors.HexColor('#0F172A'))
    univ_header = ParagraphStyle('UnivHeader', parent=styles['Normal'], fontName=BOLD_FONT, fontSize=9.5, leading=13, alignment=2, textColor=colors.HexColor('#1E3A8A'))
    meta_title = ParagraphStyle('MetaTitle', parent=styles['Normal'], fontName=BOLD_FONT, fontSize=9.5, leading=13, alignment=0, textColor=colors.HexColor('#1E3A8A'))

    # 1. Official Header Banner
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logo_path = os.path.join(base_dir, "damascus_univ_logo.png")
    logo_img = Image(logo_path, width=54, height=51.5) if os.path.exists(logo_path) else Paragraph(ar("جامعة دمشق"), title_bold)

    right_header_p = Paragraph(
        f"<b>{ar('الجمهورية العربية السورية')}</b><br/>"
        f"<b>{ar('جامعة دمشق')}</b><br/>"
        f"{ar('كلية الهندسة المعلوماتية')}",
        univ_header
    )
    
    now_str = datetime.datetime.now().strftime("%Y-%m-%d")
    left_meta_p = Paragraph(
        f"<b>{ar('كشف المسيرة الأكاديمية الشامل')}</b><br/>"
        f"{ar('السجل الأكاديمي والبيان الرسمي الموحد')}<br/>"
        f"{ar('رمز التوثيق الإلكتروني:')} DU-ITE-{career_data.get('student_university_id', '0000')}<br/>"
        f"{ar('تاريخ التوثيق:')} {now_str}",
        meta_title
    )

    header_table = Table([[left_meta_p, logo_img, right_header_p]], colWidths=[200, 70, 270])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4))

    # Golden & Navy Dividers
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1E3A8A'), spaceBefore=2, spaceAfter=2))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#D97706'), spaceBefore=0, spaceAfter=6))

    # 2. Student Identity & Comprehensive Profile Card
    linked_ids = career_data.get("all_student_ids", [career_data.get("student_university_id", "")])
    all_seats_str = " | ".join(str(x) for x in linked_ids) if linked_ids else str(career_data.get("student_university_id", ""))
    
    total_courses = career_data.get("total_courses_count", len(career_data.get("passed_courses", [])) + len(career_data.get("carried_courses", [])))
    passed_count = career_data.get("passed_courses_count", len(career_data.get("passed_courses", [])))
    carried_count = career_data.get("carried_courses_count", len(career_data.get("carried_courses", [])))
    cum_gpa = float(career_data.get("cumulative_gpa", 0.0))
    status_text = career_data.get("academic_status", "ناجح ومرفع")

    if cum_gpa >= 80:
        standing = ar("ممتاز مع مرتبة الشرف (الأولى)")
    elif cum_gpa >= 70:
        standing = ar("جيد جداً")
    elif cum_gpa >= 60:
        standing = ar("جيد")
    elif cum_gpa >= 50:
        standing = ar("مقبول")
    else:
        standing = ar("بحاجة لمعالجة")

    name_str = f"اسم الطالب: {career_data.get('student_name', '')}"
    name_p = Paragraph(f"<b>{ar(name_str)}</b>", ParagraphStyle(
        'CardName', fontName=BOLD_FONT, fontSize=11, leading=14, alignment=1, textColor=colors.white
    ))
    
    t_name_banner = Table([[name_p]], colWidths=[540])
    t_name_banner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1E3A8A')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))

    info_rows = [
        [
            f"{cum_gpa:.2f}% ({standing})",
            ar("المعدل التراكمي العام:"),
            all_seats_str,
            ar("أرقام الجلوس (كافة السنوات):")
        ],
        [
            f"{total_courses} {ar('مقرراً مسجلاً')}",
            ar("إجمالي المقررات:"),
            ar(status_text),
            ar("الحالة الأكاديمية الرسمية:")
        ],
        [
            f"{carried_count} {ar('مقررات متبقية')}" if carried_count > 0 else ar("0 (سجل خالٍ من الرسوب)"),
            ar("المقررات المتبقية / المحمولة:"),
            f"{passed_count} {ar('مقرراً بنجاح')} ({(passed_count/max(1,total_courses)*100):.1f}%)",
            ar("المقررات المنجزة بنجاح:")
        ],
        [
            f"{career_data.get('lowest_mark_overall', 0)}% - {ar(career_data.get('lowest_mark_course', ''))[:24]}",
            ar("أدنى علامة محققة:"),
            f"{career_data.get('highest_mark_overall', 0)}% - {ar(career_data.get('highest_mark_course', ''))[:24]}",
            ar("أعلى علامة محققة:")
        ]
    ]

    t_info = Table(info_rows, colWidths=[150, 120, 150, 120])
    t_info.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#F1F5F9')),
        ('BACKGROUND', (3, 0), (3, -1), colors.HexColor('#F1F5F9')),
        ('FONTNAME', (1, 0), (1, -1), BOLD_FONT),
        ('FONTNAME', (3, 0), (3, -1), BOLD_FONT),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    story.append(KeepTogether([t_name_banner, t_info]))
    story.append(Spacer(1, 8))

    # 3. High-Resolution Visual Charts & Infographics
    try:
        charts_buf = generate_career_charts(career_data)
        chart_img = Image(charts_buf, width=540, height=195)
        story.append(chart_img)
        story.append(Spacer(1, 8))
    except Exception as e:
        print("Charts generation note:", e)

    # 4. Failed / Carried Courses Section
    carried_list = career_data.get("carried_courses", [])
    if carried_list:
        c_head_p = Paragraph(f"<b>{ar('سجل المقررات الدراسية المتبقية (المحمولة) والوضع من مراسيم المساعدة')}</b>", ParagraphStyle(
            'CarriedH', fontName=BOLD_FONT, fontSize=9.5, leading=12, alignment=1, textColor=colors.white
        ))
        t_chead = Table([[c_head_p]], colWidths=[540])
        t_chead.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#991B1B')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))

        c_rows = [
            [ar("مشمول بمرسوم المساعدة"), ar("عدد المحاولات"), ar("العلامة الأخيرة"), ar("الدورة الامتحانية"), ar("اسم المقرر الدراسي")]
        ]
        for c in carried_list:
            att = c.get("attempts_count", 1)
            att_str = ar("محاولة 1") if att == 1 else f"{att} {ar('محاولات')}"
            grace_note = ar("مؤهلة للمساعدة (+1 أو +2)") if c.get("is_grace_eligible") else ar("مادة متبقية")
            c_rows.append([
                grace_note,
                att_str,
                f"{c.get('last_score', 0)}%",
                ar(c.get("session_title", "")[:24]),
                ar(c.get("course_name", ""))
            ])

        t_carried = Table(c_rows, colWidths=[90, 65, 65, 130, 190])
        t_carried.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#7F1D1D')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#FCA5A5')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#FEF2F2'), colors.white]),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ]))

        # Syrian Grace Marks Explanatory Note
        grace_candidates = career_data.get("grace_marks_eligible", [])
        grace_lines = [
            ar("• مرسوم المساعدة الجامعية السورية (قانون تنظيم الجامعات): يمنح الطالب مساعدة بدرجتين لمقرر واحد (58 أو 59) أو درجة واحدة لمقررين (59 لكل منهما) لنيل علامة النجاح 60 والترفع/التخرج.")
        ]
        if grace_candidates:
            for g in grace_candidates:
                grace_lines.append(f"• {ar('المقرر')}: {ar(g.get('course_name'))} ({ar('علامته')} {g.get('current_mark')}) -> {ar('يحتاج')} {g.get('required_grace_marks')} {ar('علامة مساعدة لاعتباره ناجحاً.')}")
        else:
            grace_lines.append(ar("• حالة الطالب الأكاديمية: لا توجد مقررات مستوفية لشروط المساعدة حالياً لكون إجمالي المساعدات المطلوبة يتجاوز الحد الأقصى للمرسوم."))

        p_grace_expl = Paragraph("<br/>".join(grace_lines), ParagraphStyle(
            'GraceExpl', fontName=FONT_NAME, fontSize=7.8, leading=11, alignment=2, textColor=colors.HexColor('#78350F')
        ))
        t_grace_box = Table([[p_grace_expl]], colWidths=[540])
        t_grace_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FEF3C7')),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#F59E0B')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))

        story.append(KeepTogether([t_chead, t_carried, Spacer(1, 3), t_grace_box]))
        story.append(Spacer(1, 8))
    else:
        # Zero Carried Courses - Clean Academic Record Banner
        clean_p = Paragraph(
            f"<b>[ {ar('سجل الشرف والتميز الأكاديمي')} ]</b> {ar('لا توجد أي مقررات متبقية أو محمولة - تم إنجاز جميع المقررات الدراسية بنجاح واقتدار (نسبة النجاح 100%).')}",
            ParagraphStyle('CleanP', fontName=BOLD_FONT, fontSize=8.5, leading=12, alignment=1, textColor=colors.HexColor('#065F46'))
        )
        t_clean = Table([[clean_p]], colWidths=[540])
        t_clean.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#ECFDF5')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#10B981')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        story.append(t_clean)
        story.append(Spacer(1, 8))

    # 5. Top 5 Highest Marks (Honors)
    passed_sorted = sorted(career_data.get("passed_courses", []), key=lambda x: x.get('final_score', 0), reverse=True)
    if passed_sorted:
        top_5 = passed_sorted[:5]
        top_headers = [ar("التقدير"), ar("العلامة"), ar("الدورة الامتحانية"), ar("اسم المقرر المتفوق به"), ar("الترتيب")]
        top_rows = [top_headers]
        for idx, tp in enumerate(top_5, 1):
            top_rows.append([
                ar("ممتاز شرف") if tp.get('final_score', 0) >= 90 else ar("ممتاز"),
                f"{tp.get('final_score', 0)}%",
                ar(tp.get("session_title", "")[:24]),
                ar(tp.get("course_name", "")),
                f"#{idx}"
            ])
        t_top = Table(top_rows, colWidths=[70, 60, 140, 220, 50])
        t_top.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#065F46')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#A7F3D0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F0FDF4'), colors.white]),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        top_title = Paragraph(f"<b>{ar('أوسمة التفوق الأكاديمي: أعلى 5 درجات محققة في المسيرة الجامعية')}</b>", ParagraphStyle(
            'TopTitle', fontName=BOLD_FONT, fontSize=9, leading=12, alignment=1, textColor=colors.HexColor('#065F46')
        ))
        story.append(KeepTogether([top_title, Spacer(1, 3), t_top]))
        story.append(Spacer(1, 10))

    # Page Break for Year-by-Year Details to keep clean structure
    story.append(PageBreak())

    # 6. Detailed Year-by-Year Academic Curriculum Breakdown
    sec_title = Paragraph(
        f"<b>{ar('السجل التفصيلي لمقررات السنوات الدراسية ومعدلاتها الرسمية')}</b>",
        ParagraphStyle('SecTitle', fontName=BOLD_FONT, fontSize=12, leading=16, alignment=1, textColor=colors.HexColor('#1E3A8A'))
    )
    story.append(sec_title)
    story.append(Spacer(1, 6))

    years_summary = career_data.get("years_summary", [])
    for yr in years_summary:
        yr_name = yr.get("year_name", "")
        yr_gpa = yr.get("annual_gpa", 0.0)
        seat_num = yr.get("seat_number", "")
        yr_highest = yr.get("highest_mark", "-")
        yr_lowest = yr.get("lowest_mark", "-")
        yr_passed = yr.get("passed_count", len(yr.get("passed_courses", [])))
        yr_carried = yr.get("carried_count", len(yr.get("carried_courses", [])))

        header_str = (
            f"<b>{ar(yr_name)}</b> | {ar('رقم الجلوس:')} {seat_num} | "
            f"{ar('معدل السنة:')} {yr_gpa}% | {ar('أعلى علامة:')} {yr_highest}% | "
            f"{ar('أدنى علامة:')} {yr_lowest}% | {ar('المقررات المنجزة:')} {yr_passed}"
        )
        if yr_carried > 0:
            header_str += f" | <font color='#FCA5A5'>{ar('متبقي:')} {yr_carried}</font>"

        p_yr_head = Paragraph(header_str, ParagraphStyle(
            'YrHead', fontName=BOLD_FONT, fontSize=9, leading=13, alignment=1, textColor=colors.white
        ))
        t_yheader = Table([[p_yr_head]], colWidths=[540])
        t_yheader.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1E3A8A')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))

        # Course Rows for this year (RTL order: Col 4 is Course Name, Col 0 is Status)
        c_table_rows = [
            [ar("الحالة الأكاديمية"), ar("المحاولات"), ar("المحصلة"), ar("الدورة الامتحانية"), ar("اسم المقرر الدراسي")]
        ]

        for p in yr.get("passed_courses", []):
            att = p.get("attempts_count", 1)
            att_str = ar("محاولة 1") if att == 1 else f"{att} {ar('محاولات')}"
            c_table_rows.append([
                ar("ناجح"),
                att_str,
                f"{p.get('final_score', 0)}%",
                ar(p.get("session_title", "")[:24]),
                ar(p.get("course_name", ""))
            ])

        for c in yr.get("carried_courses", []):
            att = c.get("attempts_count", 1)
            att_str = ar("محاولة 1") if att == 1 else f"{att} {ar('محاولات')}"
            status_c = ar("[مرفعة مساعدة]") if c.get("is_grace_eligible") else ar("مادة متبقية")
            c_table_rows.append([
                status_c,
                att_str,
                f"{c.get('last_score', 0)}%",
                ar(c.get("session_title", "")[:24]),
                ar(c.get("course_name", ""))
            ])

        t_courses = Table(c_table_rows, colWidths=[80, 60, 60, 150, 190])
        
        # Color specific rows (failed vs passed)
        row_styles = [
            ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
        ]

        # Highlight marks >= 60 in green, < 60 in red (Col 2 is Score)
        for r_idx in range(1, len(c_table_rows)):
            score_str = c_table_rows[r_idx][2].replace('%', '').strip()
            try:
                sc = float(score_str)
                if sc >= 60:
                    row_styles.append(('TEXTCOLOR', (2, r_idx), (2, r_idx), colors.HexColor('#059669')))
                    row_styles.append(('FONTNAME', (2, r_idx), (2, r_idx), BOLD_FONT))
                else:
                    row_styles.append(('TEXTCOLOR', (2, r_idx), (2, r_idx), colors.HexColor('#DC2626')))
                    row_styles.append(('FONTNAME', (2, r_idx), (2, r_idx), BOLD_FONT))
            except Exception:
                pass

        t_courses.setStyle(TableStyle(row_styles))
        story.append(KeepTogether([t_yheader, t_courses]))
        story.append(Spacer(1, 8))

    # 7. WORLD-CLASS DESIGNER SIGNATURE BOX (Exact user specification)
    story.append(Spacer(1, 14))
    dev_box_ar = Paragraph(
        f"<b>{ar('هذا الموقع تم تصميمه بواسطة المهندس عبدالرحمن قاسم صالح 0938135338')}</b><br/>"
        f"<font size='7.5'>{ar('منظومة السجل الأكاديمي والنتائج المؤتمتة - كلية الهندسة المعلوماتية - جامعة دمشق | كافة الحقوق محفوظة')}</font>",
        ParagraphStyle('DevAr', fontName=BOLD_FONT, fontSize=9.5, leading=13, alignment=1, textColor=colors.HexColor('#FEF08A'))
    )
    dev_box_en = Paragraph(
        f"<font size='8' color='#E2E8F0'><b>Designed & Developed by Eng. Abdulrahman Qasem Saleh | 0938135338</b></font>",
        ParagraphStyle('DevEn', fontName=FONT_NAME, fontSize=8, leading=11, alignment=1, textColor=colors.HexColor('#E2E8F0'))
    )

    t_dev = Table([[dev_box_ar], [dev_box_en]], colWidths=[540])
    t_dev.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0F172A')),
        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#F59E0B')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(KeepTogether([t_dev]))

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer


def generate_mark_pdf(mark_data: dict) -> io.BytesIO:
    """Generates official single course mark PDF certificate with logo and designer signature."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        'DocHeader', parent=styles['Heading1'], fontName=BOLD_FONT, fontSize=15, leading=20, alignment=1, textColor=colors.HexColor('#1E1B4B')
    )
    sub_style = ParagraphStyle(
        'DocSub', parent=styles['Normal'], fontName=FONT_NAME, fontSize=11, leading=15, alignment=1, textColor=colors.HexColor('#475569')
    )

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logo_path = os.path.join(base_dir, "damascus_univ_logo.png")
    if os.path.exists(logo_path):
        story.append(Image(logo_path, width=54, height=51.5))
        story.append(Spacer(1, 6))

    story.append(Paragraph(ar("الجمهورية العربية السورية - جامعة دمشق"), header_style))
    story.append(Paragraph(ar("كلية الهندسة المعلوماتية"), sub_style))
    story.append(Paragraph(ar("إشعار نتيجة مقرر امتحاني رسمي معتمد"), header_style))
    story.append(Spacer(1, 16))

    score = mark_data.get('total_mark', 0)
    status_text = mark_data.get("result_status", "ناجح") if score >= 60 else "راسب"

    data = [
        [ar("البيان الأكاديمي"), ar("التفاصيل الموثقة")],
        [ar("اسم الطالب الكامل"), ar(mark_data.get("student_name", ""))],
        [ar("الرقم الامتحاني / الجامعي"), str(mark_data.get("student_university_id", ""))],
        [ar("اسم المقرر الدراسي"), ar(mark_data.get("course_name", ""))],
        [ar("الدورة والجلسة الامتحانية"), ar(mark_data.get("session_title", ""))],
        [ar("درجة الامتحان العملي"), str(mark_data.get("practical_mark") if mark_data.get("practical_mark") else "-")],
        [ar("درجة الامتحان النظري"), str(mark_data.get("theoretical_mark") if mark_data.get("theoretical_mark") else "-")],
        [ar("المحصلة النهائية للمقرر"), f"{score}%"],
        [ar("النتيجة الرسمية المعتمدة"), ar(status_text)]
    ]

    t = Table(data, colWidths=[200, 320])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 10.5),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E1B4B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
    ]))
    story.append(t)
    story.append(Spacer(1, 24))

    # Developer Signature Box
    dev_box_ar = Paragraph(
        f"<b>{ar('هذا الموقع تم تصميمه بواسطة المهندس عبدالرحمن قاسم صالح 0938135338')}</b><br/>"
        f"<font size='7.5'>{ar('منظومة السجل الأكاديمي والنتائج المؤتمتة - كلية الهندسة المعلوماتية - جامعة دمشق')}</font>",
        ParagraphStyle('DevArM', fontName=BOLD_FONT, fontSize=9, leading=12, alignment=1, textColor=colors.HexColor('#FEF08A'))
    )
    t_dev = Table([[dev_box_ar]], colWidths=[520])
    t_dev.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0F172A')),
        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#F59E0B')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_dev)

    doc.build(story)
    buffer.seek(0)
    return buffer
