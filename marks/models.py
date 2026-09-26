from django.db import models


class AcademicYear(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Course(models.Model):
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="courses")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="courses")
    name = models.CharField(max_length=150, db_index=True)
    semester = models.IntegerField(default=1)
    has_practical = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ExamSession(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="sessions")
    session_title = models.CharField(max_length=150)
    academic_year_str = models.CharField(max_length=30, db_index=True)
    semester_num = models.IntegerField(default=1)
    source_type = models.CharField(max_length=30, default="API")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.session_title


class StudentMark(models.Model):
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name="marks")
    student_university_id = models.CharField(max_length=50, db_index=True)
    student_name = models.CharField(max_length=200)
    student_name_clean = models.CharField(max_length=200, db_index=True)
    practical_mark = models.FloatField(default=0.0)
    theoretical_mark = models.FloatField(default=0.0)
    total_mark = models.FloatField(db_index=True)
    result_status = models.CharField(max_length=30)
    is_grace_eligible = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['student_name_clean']),
            models.Index(fields=['student_university_id']),
            models.Index(fields=['session', 'total_mark']),
        ]

    def __str__(self):
        return f"{self.student_name} - {self.total_mark}"


class GDriveSyncLog(models.Model):
    file_id = models.CharField(max_length=100, unique=True, db_index=True)
    file_name = models.CharField(max_length=255)
    records_count = models.IntegerField(default=0)
    status = models.CharField(max_length=50, default="SUCCESS")
    synced_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file_name
