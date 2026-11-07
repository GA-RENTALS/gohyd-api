from django.urls import path

from .views import LogoutView, MeView, PasswordLoginView, RequestOTPView, TenantTokenRefreshView, VerifyOTPView

urlpatterns = [
    path('auth/request-otp/', RequestOTPView.as_view(), name='request-otp'),
    path('auth/verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('auth/password-login/', PasswordLoginView.as_view(), name='password-login'),
    path('auth/refresh/', TenantTokenRefreshView.as_view(), name='token-refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
]
