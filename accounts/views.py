import random
from datetime import timedelta
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, PasswordResetOTP
from .serializers import UserRegisterSerializer, UserProfileSerializer
from services.email_service import send_admin_alert_async, send_otp_email_async
from services.telegram_service import send_telegram_alert_async


class RegisterView(APIView):
    """Registers a new student and alerts the admin via Email & Telegram."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            total_students = User.objects.count()

            # Trigger email to admin
            send_admin_alert_async(
                student_name=user.full_name,
                phone_number=user.phone_number,
                total_students_count=total_students
            )

            # Trigger instant Telegram notification to admin
            send_telegram_alert_async(
                student_name=user.full_name,
                phone_number=user.phone_number,
                total_students_count=total_students
            )

            refresh = RefreshToken.for_user(user)
            user_payload = {
                "id": user.id,
                "user_id": user.id,
                "full_name": user.full_name,
                "phone_number": user.phone_number,
                "email": user.email,
                "linked_student_id": user.linked_student_id
            }
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
                "user": user_payload,
                **user_payload
            }, status=status.HTTP_201_CREATED)
        errors = serializer.errors
        err_msg = "فشل إنشاء الحساب."
        if 'phone_number' in errors or 'username' in errors:
            err_msg = "رقم الهاتف هذا مسجل بالفعل. يرجى تسجيل الدخول أو استخدام رقم آخر."
        return Response({"error": err_msg, "detail": err_msg, "errors": errors}, status=status.HTTP_400_BAD_REQUEST)


class ForgotPasswordView(APIView):
    """Dispatches 6-digit OTP via Gmail."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        identifier = request.data.get("phone_number_or_email", "").strip()
        user = User.objects.filter(phone_number=identifier).first() or User.objects.filter(email=identifier).first()
        if not user:
            return Response({"error": "المستخدم غير مسجل"}, status=404)

        otp_code = str(random.randint(100000, 999999))
        PasswordResetOTP.objects.create(
            user=user,
            otp_code=otp_code,
            expires_at=timezone.now() + timedelta(minutes=10)
        )

        target_email = user.email or getattr(settings, 'ADMIN_EMAIL', 'eng.abdulrahman.saleh2003@gmail.com')
        send_otp_email_async(target_email, otp_code, user.full_name)

        return Response({"message": "تم إرسال رمز الأمان OTP بنجاح.", "expires_in_minutes": 10})


class ResetPasswordView(APIView):
    """Validates OTP and updates password."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        phone = request.data.get("phone_number", "").strip()
        otp = request.data.get("otp_code", "").strip()
        new_pwd = request.data.get("new_password", "")

        user = User.objects.filter(phone_number=phone).first()
        if not user:
            return Response({"error": "المستخدم غير موجود"}, status=404)

        otp_record = PasswordResetOTP.objects.filter(
            user=user,
            otp_code=otp,
            is_used=False,
            expires_at__gte=timezone.now()
        ).first()

        if not otp_record:
            return Response({"error": "رمز التحقق غير صحيح أو منتهي الصلاحية."}, status=400)

        otp_record.is_used = True
        otp_record.save()
        user.set_password(new_pwd)
        user.save()

        return Response({"message": "تم تحديث كلمة المرور بنجاح. يمكنك الآن تسجيل الدخول."})


class ProfileView(APIView):
    """Current authenticated user profile."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserProfileSerializer(request.user).data)
