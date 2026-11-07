from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views import home
from payments.views import razorpay_webhook

admin.site.site_header = 'GoHyderabad'


def admin_entry(request):
    """/admin/ forwards to the Next.js panel; /admin/?classic=1 opens the stock Django admin home (used after Django-admin login)."""
    if request.GET.get('classic'):
        return admin.site.admin_view(admin.site.index)(request)
    return RedirectView.as_view(url=settings.ADMIN_PANEL_URL, permanent=False)(request)


urlpatterns = [
    path('', home, name='home'),
    # The staff UI is the Next.js admin panel; the bare Django admin index just forwards there.
    # (Deep links like /admin/<app>/<model>/ still work as a break-glass fallback.)
    path('admin/', admin_entry),
    path('admin/', admin.site.urls),
    path('api/v1/', include('admin_api.urls')),
    path('tinymce/', include('tinymce.urls')),
    path('api/v1/', include('accounts.urls')),
    path('api/v1/', include('content.urls')),
    path('api/v1/', include('trips.urls')),
    path('api/v1/', include('bookings.urls')),
    path('api/v1/', include('crm.urls')),
    path('api/v1/', include('tracking.urls')),
    path('webhooks/razorpay/', razorpay_webhook),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema')),
]
if settings.SERVE_MEDIA:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
