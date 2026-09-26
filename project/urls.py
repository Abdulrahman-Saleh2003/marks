from django.contrib import admin
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from accounts.views import RegisterView, ForgotPasswordView, ResetPasswordView, ProfileView
from accounts.serializers import CustomTokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from marks.views import (
    SmartMatchView, ClaimIdentityView, StudentSearchView,
    StudentCareerSummaryView, Top30LeaderboardView, CourseToppersView,
    SingleMarkPDFView, CareerTranscriptPDFView, GDriveSyncTriggerView
)

class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


from django.http import JsonResponse

def api_root(request):
    return JsonResponse({
        'status': 'online',
        'project': 'ITE Damascus University Marks Portal API',
        'university': 'Damascus University - Faculty of Information Technology Engineering',
        'author': 'Abdulrahman Saleh',
        'endpoints': {
            'admin': '/admin/',
            'search': '/api/search/students/',
            'leaderboards': '/api/leaderboards/top30/',
            'auth_login': '/api/auth/login/',
            'auth_register': '/api/auth/register/'
        }
    })

urlpatterns = [
    path('', api_root, name='api_root'),
    path('admin/', admin.site.urls),

    # Auth Endpoints
    path('api/auth/register/', RegisterView.as_view(), name='register'),
    path('api/auth/login/', CustomLoginView.as_view(), name='login'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('api/auth/reset-password/', ResetPasswordView.as_view(), name='reset_password'),
    path('api/auth/me/', ProfileView.as_view(), name='profile'),

    # Smart Identity on Home
    path('api/students/smart-match/', SmartMatchView.as_view(), name='smart_match'),
    path('api/students/claim-identity/', ClaimIdentityView.as_view(), name='claim_identity'),

    # Universal Search
    path('api/search/students/', StudentSearchView.as_view(), name='search_students'),

    # Career Analytics & Syrian Grace Marks
    path('api/analytics/student/<str:student_id>/summary/', StudentCareerSummaryView.as_view(), name='career_summary'),

    # Leaderboards
    path('api/leaderboards/top30/', Top30LeaderboardView.as_view(), name='top30'),
    path('api/leaderboards/course-toppers/', CourseToppersView.as_view(), name='course_toppers'),

    # PDF Reports
    path('api/reports/mark/<int:mark_id>/pdf/', SingleMarkPDFView.as_view(), name='mark_pdf'),
    path('api/reports/career/<str:student_id>/pdf/', CareerTranscriptPDFView.as_view(), name='transcript_pdf'),

    # Google Drive Auto-Sync
    path('api/sync/gdrive/trigger/', GDriveSyncTriggerView.as_view(), name='gdrive_sync_trigger'),
]
