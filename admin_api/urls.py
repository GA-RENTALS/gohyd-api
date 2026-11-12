from django.urls import path

from . import home, overview, views

urlpatterns = [
    path('admin/session/', views.AdminSessionView.as_view(), name='admin-session'),
    path('admin/modules/', views.AdminModuleCatalogView.as_view(), name='admin-modules'),
    path('admin/dashboard/', views.AdminDashboardView.as_view(), name='admin-dashboard'),
    path('admin/resources/<slug:resource_key>/schema/', views.AdminResourceSchemaView.as_view(), name='admin-resource-schema'),
    path('admin/resources/<slug:resource_key>/', views.AdminResourceCollectionView.as_view(), name='admin-resource-list'),
    path('admin/resources/<slug:resource_key>/<str:pk>/', views.AdminResourceDetailView.as_view(), name='admin-resource-detail'),
    path('admin/home/', home.HomeView.as_view(), name='admin-home'),
    path('admin/counts/', home.CountsView.as_view(), name='admin-counts'),
    path('admin/search/', home.SearchView.as_view(), name='admin-search'),
    path('admin/lists/bookings/', home.BookingListView.as_view(), name='admin-list-bookings'),
    path('admin/lists/payments/', home.PaymentListView.as_view(), name='admin-list-payments'),
    path('admin/lists/customers/', home.CustomerListView.as_view(), name='admin-list-customers'),
    path('admin/customers/<str:pk>/', home.CustomerDetailView.as_view(), name='admin-customer'),
    path('admin/catalog/<slug:kind>/', overview.CatalogView.as_view(), name='admin-catalog'),
    path('admin/overview/trips/<str:pk>/', overview.TripOverviewView.as_view(), name='admin-trip-overview'),
    path('admin/overview/events/<str:pk>/', overview.EventOverviewView.as_view(), name='admin-event-overview'),
    path('admin/actions/<slug:action>/', views.StaffActionView.as_view(), name='admin-action'),
]
