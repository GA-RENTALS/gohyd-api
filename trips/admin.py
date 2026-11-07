from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, StackedInline, TabularInline

from content.admin import ApprovalActionsMixin, PublishableAdmin
from . import models as m


class ScheduleInline(TabularInline):
    model = m.TripSchedule
    extra = 0
    fields = ('starts_at', 'ends_at', 'capacity', 'seats_booked', 'price_per_participant', 'is_open', 'advance_basis_points', 'balance_due_days_before')
    readonly_fields = ('seats_booked',)


class PickupInline(TabularInline):
    model = m.TripPickupPoint
    extra = 0


class TripTranslationInline(StackedInline):
    model = m.TripTranslation
    extra = 0
    fields = ('language', 'title', 'summary', 'body', 'seo_title', 'seo_description', 'localized_slug', 'status')


class PolicyInline(TabularInline):
    model = m.TripPolicy
    extra = 0


class IncInline(TabularInline):
    model = m.TripInclusion
    extra = 0


class ExcInline(TabularInline):
    model = m.TripExclusion
    extra = 0


@admin.register(m.Trip)
class TripAdmin(PublishableAdmin):
    list_display = ('slug', 'status', 'operational_status', 'advance_basis_points', 'balance_due_days_before', 'gst_configuration')
    list_filter = ('status', 'operational_status', 'categories')
    search_fields = ('slug', 'translations__title')
    inlines = [TripTranslationInline, ScheduleInline, PickupInline, PolicyInline, IncInline, ExcInline]
    actions = PublishableAdmin.actions + ['pause', 'reopen']

    @admin.action(description='Pause bookings (operational; no approval needed)')
    def pause(self, request, qs):
        for t in qs:
            m.TripStatusHistory.objects.create(trip=t, field='operational', from_status=t.operational_status, to_status='PAUSED', actor=request.user)
        qs.update(operational_status=m.Trip.Operational.PAUSED)

    @admin.action(description='Re-open bookings')
    def reopen(self, request, qs):
        for t in qs:
            m.TripStatusHistory.objects.create(trip=t, field='operational', from_status=t.operational_status, to_status='OPEN', actor=request.user)
        qs.update(operational_status=m.Trip.Operational.OPEN)


@admin.register(m.TripTranslation)
class TripTranslationAdmin(ApprovalActionsMixin, SimpleHistoryAdmin, ModelAdmin):
    list_display = ('trip', 'language', 'title', 'status')
    list_filter = ('language', 'status')


@admin.register(m.TripSchedule)
class TripScheduleAdmin(ModelAdmin):
    list_display = ('trip', 'starts_at', 'capacity', 'seats_booked', 'price_per_participant', 'is_open')
    list_filter = ('is_open', 'trip')
    readonly_fields = ('seats_booked',)
    date_hierarchy = 'starts_at'


class EventTranslationInline(StackedInline):
    model = m.EventTranslation
    extra = 0


class EventScheduleInline(TabularInline):
    model = m.EventSchedule
    extra = 0


@admin.register(m.Event)
class EventAdmin(PublishableAdmin):
    list_display = ('slug', 'category', 'status')
    inlines = [EventTranslationInline, EventScheduleInline]


for model in (m.TripCategory, m.TripPricingRule, m.TripItinerary, m.TripAssignment, m.EventRegistration, m.EventParticipant, m.EventAttendance):
    admin.site.register(model, type(f'{model.__name__}Admin', (ModelAdmin,), {}))
admin.site.register(m.TripStatusHistory, type('TripStatusHistoryAdmin', (ModelAdmin,), {'has_add_permission': lambda s, r: False}))
