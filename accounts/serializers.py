from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User, PasswordResetOTP


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['id', 'phone_number', 'full_name', 'email', 'password']

    def create(self, validated_data):
        user = User(
            phone_number=validated_data['phone_number'].strip(),
            username=validated_data['phone_number'].strip(),
            full_name=validated_data['full_name'].strip(),
            email=validated_data.get('email', '').strip() or None
        )
        user.set_password(validated_data['password'])
        user.save()
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom SimpleJWT serializer using phone_number."""
    username_field = 'phone_number'

    def validate(self, attrs):
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
