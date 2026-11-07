from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from tenancy.models import TenantMembership
from .models import CustomerProfile, User, normalize_phone


class PhoneField(serializers.CharField):
    def to_internal_value(self, data):
        try:
            return normalize_phone(super().to_internal_value(data))
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)


class RequestOTPSerializer(serializers.Serializer):
    phone_number = PhoneField(max_length=20)


class VerifyOTPSerializer(serializers.Serializer):
    phone_number = PhoneField(max_length=20)
    otp = serializers.RegexField(r'^\d{6}$', error_messages={'invalid': 'Code must be 6 digits.'})


class PasswordLoginSerializer(serializers.Serializer):
    phone_number = PhoneField(max_length=20)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TenantTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            raise serializers.ValidationError('A verified operator domain is required.')

        try:
            refresh = RefreshToken(attrs['refresh'])
        except TokenError as exc:
            raise serializers.ValidationError('Token is invalid or expired.') from exc

        if str(refresh.get('tenant_id', '')) != str(tenant.pk):
            raise serializers.ValidationError('The token is not valid for this operator.')

        user_id = refresh.get(api_settings.USER_ID_CLAIM)
        user = User.objects.filter(
            **{api_settings.USER_ID_FIELD: user_id},
            is_active=True,
            deleted_at__isnull=True,
        ).first()
        if user is None:
            raise serializers.ValidationError('The token user is no longer active.')
        if not user.is_superuser and not TenantMembership.objects.filter(
            tenant=tenant, user=user, is_active=True,
        ).exists():
            raise serializers.ValidationError('Active membership in this operator is required.')

        return super().validate(attrs)


class CustomerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerProfile
        fields = ('billing_name', 'billing_gstin', 'billing_address', 'notify_whatsapp', 'notify_email', 'notify_sms', 'marketing_opt_in')


class ProfileSerializer(serializers.ModelSerializer):
    customer_profile = CustomerProfileSerializer(required=False)

    class Meta:
        model = User
        fields = ('id', 'phone_number', 'full_name', 'email', 'preferred_language', 'is_profile_complete', 'kind', 'customer_profile')
        read_only_fields = ('id', 'phone_number', 'is_profile_complete', 'kind')

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None)
        profile = None
        if tenant is not None:
            profile = CustomerProfile.objects.filter(user=instance, tenant=tenant).first()
        data['customer_profile'] = CustomerProfileSerializer(profile).data if profile else None
        return data

    def update(self, instance, validated):
        prof = validated.pop('customer_profile', None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if prof is not None:
            tenant = getattr(self.context.get('request'), 'tenant', None)
            if tenant is None:
                raise serializers.ValidationError('A verified operator domain is required.')
            obj, _ = CustomerProfile.objects.get_or_create(user=instance, tenant=tenant)
            for k, v in prof.items():
                setattr(obj, k, v)
            obj.save()
        return instance
