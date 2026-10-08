import re
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User, PasswordResetOTP


def normalize_phone_number(raw):
    """Sanitizes, validates, and formats mobile numbers (Syrian standard 09xxxxxxxx or valid international)."""
    if not raw:
        return ""
    # Convert Arabic-indic numerals to standard digits
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    cleaned = ""
    for ch in str(raw).strip():
        if ch in arabic_digits:
            cleaned += str(arabic_digits.index(ch))
        elif ch.isdigit() or ch == '+':
            cleaned += ch

    cleaned = cleaned.replace(" ", "").replace("-", "")

    # Syrian mobile pattern: 09xxxxxxxx, +9639xxxxxxxx, 009639xxxxxxxx, 9639xxxxxxxx
    syrian_match = re.match(r'^(?:\+963|00963|963)?(0?9\d{8})$', cleaned)
    if syrian_match:
        p = syrian_match.group(1)
        if not p.startswith('0'):
            p = '0' + p
        return p

    # Standard international mobile format (9 to 15 digits)
    if re.match(r'^\+?[1-9]\d{8,14}$', cleaned):
        return cleaned

    return ""


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['id', 'phone_number', 'full_name', 'email', 'password']

    def validate_phone_number(self, value):
        norm = normalize_phone_number(value)
        if not norm:
            raise serializers.ValidationError("يرجى إدخال رقم هاتف محمول صالح (مثال: 0938135338).")
        if User.objects.filter(phone_number=norm).exists():
            raise serializers.ValidationError("رقم الهاتف هذا مسجل بالفعل. يرجى تسجيل الدخول أو استخدام رقم آخر.")
        return norm

    def validate_full_name(self, value):
        val = value.strip()
        if len(val) < 4:
            raise serializers.ValidationError("يرجى إدخال اسمك الكامل بشكل واضح.")
        # Must have at least 2 words
        words = val.split()
        if len(words) < 2:
            raise serializers.ValidationError("يرجى إدخال الاسم والكنية على الأقل (مثال: أحمد المحمد).")
        # Reject if pure digits or symbols
        if not re.search(r'[\u0600-\u06FFa-zA-Z]', val):
            raise serializers.ValidationError("الاسم يجب أن يحتوي على أحرف حقيقية.")
        if re.search(r'[\d!@#$%^&*()_+={}\[\]:;"\'<>,.?/\\|~`]', val):
            raise serializers.ValidationError("يرجى إدخال الاسم بدون أرقام أو رموز خاصة.")
        return val

    def create(self, validated_data):
        user = User(
            phone_number=validated_data['phone_number'],
            username=validated_data['phone_number'],
            full_name=validated_data['full_name'].strip(),
            email=validated_data.get('email', '').strip() or None
        )
        user.set_password(validated_data['password'])
        user.save()
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom SimpleJWT serializer using phone_number with automatic normalization."""
    username_field = 'phone_number'

    def validate(self, attrs):
        # Normalize phone before authenticating
        raw_phone = attrs.get(self.username_field, '')
        norm = normalize_phone_number(raw_phone)
        if norm:
            attrs[self.username_field] = norm

        data = super().validate(attrs)
        user_payload = {
            "id": self.user.id,
            "user_id": self.user.id,
            "full_name": self.user.full_name,
            "phone_number": self.user.phone_number,
            "email": self.user.email,
            "linked_student_id": self.user.linked_student_id
        }
        data['user'] = user_payload
        data['user_id'] = self.user.id
        data['full_name'] = self.user.full_name
        data['phone_number'] = self.user.phone_number
        data['linked_student_id'] = self.user.linked_student_id
        return data


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'phone_number', 'full_name', 'email', 'linked_student_id', 'date_joined']
