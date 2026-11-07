from django.urls import path

from . import views

urlpatterns = [
    path('admin/session/', views.AdminSessionView.as_view(), name='admin-session'),
    path('admin/modules/', views.AdminModuleCatalogView.as_view(), name='admin-modules'),
    path('admin/dashboard/', views.AdminDashboardView.as_view(), name='admin-dashboard'),
    path('admin/resources/<slug:resource_key>/schema/', views.AdminResourceSchemaView.as_view(), name='admin-resource-schema'),
    path('admin/resources/<slug:resource_key>/', views.AdminResourceCollectionView.as_view(), name='admin-resource-list'),
    path('admin/resources/<slug:resource_key>/<str:pk>/', views.AdminResourceDetailView.as_view(), name='admin-resource-detail'),
    path('admin/actions/<slug:action>/', views.StaffActionView.as_view(), name='admin-action'),
]
