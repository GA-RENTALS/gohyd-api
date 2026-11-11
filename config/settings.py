"""GoHyderabad settings. Structure follows GoRentals (same stack: Django + DRF + Unfold + Celery + Redis + Postgres)."""
import os
import ipaddress
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def _bool(name, default='False'):
    return os.getenv(name, default).strip().lower() in {'1', 'true', 'yes', 'on'}


DEBUG = _bool('DEBUG')
SECRET_KEY = os.getenv('SECRET_KEY', '').strip()
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('SECRET_KEY must be set when DEBUG is False.')
    SECRET_KEY = 'dev-only-insecure-key-do-not-deploy'

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '').split(',') if h.strip()]
if not ALLOWED_HOSTS and DEBUG:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
if DEBUG and 'test' in sys.argv and 'testserver' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('testserver')
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured('ALLOWED_HOSTS must be set when DEBUG is False.')

CSRF_TRUSTED_ORIGINS =[
        'http://3.110.175.214',
    'http://127.0.0.1',
    'http://localhost'
    ]+[o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]
try:
    TRUSTED_PROXY_NETWORKS = tuple(
        ipaddress.ip_network(ip.strip(), strict=False)
        for ip in os.getenv('TRUSTED_PROXY_IPS', '').split(',')
        if ip.strip()
    )
except ValueError as exc:
    raise ImproperlyConfigured('TRUSTED_PROXY_IPS must contain valid IP addresses or CIDR networks.') from exc
COOKIES_SECURE = _bool('COOKIES_SECURE', str(not DEBUG))
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = COOKIES_SECURE
SECURE_SSL_REDIRECT = _bool('SECURE_SSL_REDIRECT', str(not DEBUG))
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0' if DEBUG else '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG and _bool('SECURE_HSTS_INCLUDE_SUBDOMAINS')
SECURE_HSTS_PRELOAD = not DEBUG and _bool('SECURE_HSTS_PRELOAD')
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('DATA_UPLOAD_MAX_MEMORY_SIZE', str(2 * 1024 * 1024)))
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('FILE_UPLOAD_MAX_MEMORY_SIZE', str(5 * 1024 * 1024)))
MAX_FILE_UPLOAD_SIZE = int(os.getenv('MAX_FILE_UPLOAD_SIZE', str(5 * 1024 * 1024)))
MAX_REQUEST_BODY_BYTES = int(os.getenv('MAX_REQUEST_BODY_BYTES', str(10 * 1024 * 1024)))
FILE_UPLOAD_HANDLERS = [
    'core.upload_handlers.MaxFileSizeUploadHandler',
    'django.core.files.uploadhandler.MemoryFileUploadHandler',
    'django.core.files.uploadhandler.TemporaryFileUploadHandler',
]

INSTALLED_APPS = [
    'unfold',
    'unfold.contrib.filters',
    'django.contrib.humanize',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'drf_spectacular',
    'django_filters',
    'simple_history',
    'tinymce',
    # local apps
    'core',
    'accounts',
    'content',
    'trips',
    'bookings',
    'payments',
    'operations',
    'crm',
    'tracking',
    'notifications',
    'tenancy',
    'admin_api',
]
AUTH_USER_MODEL = 'accounts.User'
TENANT_RLS_ENABLED = _bool('TENANT_RLS_ENABLED', 'True')

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'core.middleware.RequestSizeLimitMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'tenancy.middleware.TenantContextMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]


def _database_from_url(url):
    p = urlparse(url)
    if p.scheme not in {'postgres', 'postgresql'}:
        raise ImproperlyConfigured('POSTGRES_URL must start with postgres:// or postgresql://')
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(p.path.lstrip('/')), 'USER': unquote(p.username or ''), 'PASSWORD': unquote(p.password or ''),
        'HOST': p.hostname or '', 'PORT': str(p.port or ''), 'CONN_MAX_AGE': 60,
        'ATOMIC_REQUESTS': False,
    }


_pg = os.getenv('POSTGRES_URL', '').strip()
if not _pg:
    raise ImproperlyConfigured('POSTGRES_URL must be set, e.g. postgres://user:password@localhost:5432/gohyderabad')
DATABASES = {'default': _database_from_url(_pg)}
if DEBUG and _bool('POSTGRES_ALLOW_OLD'):   # local PostgreSQL < 15 only; see config/pgcompat/base.py
    DATABASES['default']['ENGINE'] = 'config.pgcompat'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_REDIRECT_URL = '/admin/?classic=1'   # Django-admin login lands on the Django admin, not the Next.js panel
ADMIN_PANEL_URL = os.getenv('ADMIN_PANEL_URL', 'http://localhost:3000/admin')   # Next.js staff panel

LANGUAGE_CODE = 'en-us'
LANGUAGES = [('en', 'English'), ('te', 'Telugu'), ('hi', 'Hindi')]
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True  # stored in UTC

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = 'media/'
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', BASE_DIR / 'media'))
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME', '').strip()
SERVE_MEDIA = not AWS_STORAGE_BUCKET_NAME and (DEBUG or _bool('SERVE_MEDIA'))
_uploads = {'BACKEND': 'django.core.files.storage.FileSystemStorage'}
if AWS_STORAGE_BUCKET_NAME:  # section 2: files on S3 (served through CloudFront if AWS_S3_CUSTOM_DOMAIN is set)
    AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME', 'ap-south-1').strip() or None
    AWS_S3_CUSTOM_DOMAIN = os.getenv('AWS_S3_CUSTOM_DOMAIN', '').strip() or None
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = False
    _uploads = {'BACKEND': 'storages.backends.s3.S3Storage'}
STORAGES = {'default': _uploads, 'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Business defaults. The live values are admin-editable (core.Setting); these are only first-run fallbacks.
DEFAULT_ADVANCE_BASIS_POINTS = int(os.getenv('DEFAULT_ADVANCE_BASIS_POINTS', '3000'))     # 30%: placeholder, not a business decision
DEFAULT_BALANCE_DUE_DAYS_BEFORE = int(os.getenv('DEFAULT_BALANCE_DUE_DAYS_BEFORE', '7'))  # placeholder
CURRENCY = 'INR'

# Sign-in codes (section 4.1)
OTP_TTL_SECONDS = int(os.getenv('OTP_TTL_SECONDS', '300'))
OTP_RESEND_SECONDS = int(os.getenv('OTP_RESEND_SECONDS', '45'))
OTP_MAX_ATTEMPTS = int(os.getenv('OTP_MAX_ATTEMPTS', '5'))
OTP_LOG_IN_CONSOLE = DEBUG and not os.getenv('WHATSAPP_API_URL')
OTP_SEND_INLINE = DEBUG   # development: send the code during the request, so no Celery worker is needed

RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                      'LOCATION': os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/1')}}
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BEAT_SCHEDULE = {
    'outbox-relay': {'task': 'core.tasks.relay_outbox', 'schedule': 5.0},
    'balance-reminders': {'task': 'notifications.tasks.queue_balance_reminders', 'schedule': 3600.0},
    'trip-reminders': {'task': 'notifications.tasks.queue_trip_reminders', 'schedule': 3600.0},
}

CORS_ALLOWED_ORIGINS = [o.strip() for o in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]
CORS_ALLOW_CREDENTIALS = False

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'tenancy.authentication.TenantJWTAuthentication',
        'tenancy.authentication.TenantSessionAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'core.throttling.TrustedAnonRateThrottle',
        'core.throttling.TrustedUserRateThrottle',
        'core.throttling.TrustedScopedRateThrottle',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': os.getenv('API_ANON_RATE', '60/minute'),
        'user': os.getenv('API_USER_RATE', '300/minute'),
        'otp_request': '10/hour',
        'otp_verify': '30/hour',
        'password_login': '20/hour',
        'track': '600/hour',
        'enquiry': '20/hour',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 12,
}
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}
SPECTACULAR_SETTINGS = {
    'TITLE': 'GoHyderabad API',
    'DESCRIPTION': 'Trips, checkout, bookings, payments, CMS, CRM, tracking and analytics for GoHyderabad.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

TINYMCE_DEFAULT_CONFIG = {
    'license_key': 'gpl', 'height': 520, 'promotion': False, 'branding': False,
    'plugins': 'advlist autolink lists link image table code fullscreen wordcount',
    'toolbar': 'undo redo | blocks | bold italic | bullist numlist | link image table | removeformat code fullscreen',
    'block_formats': 'Paragraph=p; Heading 2=h2; Heading 3=h3',
    'relative_urls': False, 'convert_urls': False,
}

UNFOLD = {
    'SITE_TITLE': 'GoHyderabad admin',
    'SITE_HEADER': 'GoHyderabad',
    'SITE_SUBHEADER': 'Admin workspace',
    'SITE_URL': os.getenv('FRONTEND_ORIGIN', 'http://localhost:3000'),
    'SHOW_HISTORY': True,
    'SHOW_VIEW_ON_SITE': False,
    'COMMAND': {'search_models': True, 'show_history': True},
    'COLORS': {'primary': {  # GoHyderabad gold/forest palette (gold = 500)
        '50': '#fdf7ea', '100': '#faedcb', '200': '#f4d994', '300': '#edc25e', '400': '#e6ad49',
        '500': '#d4902c', '600': '#b87021', '700': '#955220', '800': '#7a4222', '900': '#66381f', '950': '#3a1c0d',
    }},
    'SIDEBAR': {
        'show_search': True,
        'show_all_applications': False,
        'navigation': [
            {
                'title': 'Daily work',
                'separator': True,
                'collapsible': False,
                'items': [
                    {'title': 'Bookings', 'icon': 'confirmation_number', 'link': reverse_lazy('admin:bookings_booking_changelist'), 'permission': lambda request: request.user.has_perm('bookings.view_booking')},
                    {'title': 'Checkout orders', 'icon': 'shopping_cart', 'link': reverse_lazy('admin:bookings_checkoutorder_changelist'), 'permission': lambda request: request.user.has_perm('bookings.view_checkoutorder')},
                    {'title': 'Trip dates', 'icon': 'calendar_month', 'link': reverse_lazy('admin:trips_tripschedule_changelist'), 'permission': lambda request: request.user.has_perm('trips.view_tripschedule')},
                    {'title': 'Trips', 'icon': 'map', 'link': reverse_lazy('admin:trips_trip_changelist'), 'permission': lambda request: request.user.has_perm('trips.view_trip')},
                ],
            },
            {
                'title': 'Payments',
                'separator': True,
                'collapsible': False,
                'items': [
                    {'title': 'Payments', 'icon': 'payments', 'link': reverse_lazy('admin:payments_payment_changelist'), 'permission': lambda request: request.user.has_perm('payments.view_payment')},
                    {'title': 'Refunds', 'icon': 'currency_exchange', 'link': reverse_lazy('admin:payments_refund_changelist'), 'permission': lambda request: request.user.has_perm('payments.view_refund')},
                ],
            },
            {
                'title': 'People & support',
                'separator': True,
                'collapsible': False,
                'items': [
                    {'title': 'Customers and staff', 'icon': 'group', 'link': reverse_lazy('admin:accounts_user_changelist'), 'permission': lambda request: request.user.has_perm('accounts.view_user')},
                    {'title': 'Support tickets', 'icon': 'support_agent', 'link': reverse_lazy('admin:crm_supportticket_changelist'), 'permission': lambda request: request.user.has_perm('crm.view_supportticket')},
                ],
            },
            {
                'title': 'Manage the business',
                'separator': True,
                'collapsible': False,
                'items': [
                    {'title': 'Vehicles', 'icon': 'airport_shuttle', 'link': reverse_lazy('admin:operations_vehicle_changelist'), 'permission': lambda request: request.user.has_perm('operations.view_vehicle')},
                    {'title': 'Vendors', 'icon': 'store', 'link': reverse_lazy('admin:operations_vendor_changelist'), 'permission': lambda request: request.user.has_perm('operations.view_vendor')},
                    {'title': 'Website pages', 'icon': 'article', 'link': reverse_lazy('admin:content_cmspage_changelist'), 'permission': lambda request: request.user.has_perm('content.view_cmspage')},
                    {'title': 'Destinations', 'icon': 'location_on', 'link': reverse_lazy('admin:content_destination_changelist'), 'permission': lambda request: request.user.has_perm('content.view_destination')},
                ],
            },
            {
                'title': 'Administration',
                'separator': True,
                'collapsible': False,
                'items': [
                    {'title': 'Business settings', 'icon': 'settings', 'link': reverse_lazy('admin:core_setting_changelist'), 'permission': lambda request: request.user.has_perm('core.view_setting')},
                    {'title': 'Audit log', 'icon': 'history', 'link': reverse_lazy('admin:core_auditlog_changelist'), 'permission': lambda request: request.user.has_perm('core.view_auditlog')},
                    {'title': 'All Django models', 'icon': 'apps', 'link': '/admin/?classic=1'},
                ],
            },
        ],
    },
}
