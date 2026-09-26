from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone


class User(AbstractUser):
    """Custom User Model using phone number as unique identifier."""
    username = models.CharField(max_length=150, unique=False, blank=True)
    phone_number = models.CharField(max_length=30, unique=True, db_index=True)
    full_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True, null=True)
    linked_student_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)

    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"


class PasswordResetOTP(models.Model):
    """Temporary 6-digit OTP code for password recovery."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_resets")
    otp_code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return not self.is_used and timezone.now() <= self.expires_at
