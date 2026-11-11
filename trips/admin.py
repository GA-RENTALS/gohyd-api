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


@admin.register(m.EventTranslation)
class EventTranslationAdmin(ApprovalActionsMixin, ModelAdmin):
    list_display = ('event', 'language', 'title', 'status')
    list_filter = ('language', 'status')


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
    fields = ('starts_at', 'ends_at', 'capacity', 'is_date_locked', 'time_tbd')


class EventItineraryInline(TabularInline):
    model = m.EventItinerary
    extra = 0


class EventFormatDetailInline(TabularInline):
    model = m.EventFormatDetail
    extra = 0
    fields = ('label_en', 'value_en', 'label_te', 'value_te', 'label_hi', 'value_hi', 'sort_order')


class EventHighlightInline(TabularInline):
    model = m.EventHighlight
    extra = 0
    fields = ('text_en', 'text_te', 'text_hi', 'sort_order')


class EventFAQInline(StackedInline):
    model = m.EventFAQ
    extra = 0


class EventRuleInline(TabularInline):
    model = m.EventRule
    extra = 0
    fields = ('text_en', 'text_te', 'text_hi', 'sort_order')


@admin.register(m.EventRegistration)
class EventRegistrationAdmin(ModelAdmin):
    list_display = ('reference', 'contact_name', 'contact_phone', 'schedule', 'participant_count', 'total_amount',
                    'status', 'reserved_until', 'created_at')
    list_filter = ('status', 'source', 'schedule__event')
    search_fields = ('reference', 'contact_name', 'contact_phone')
    readonly_fields = ('reference', 'total_amount', 'confirmed_at', 'cancelled_at', 'created_at')
    actions = ('confirm_bookings', 'cancel_bookings')

    @admin.action(description='Confirm selected bookings')
    def confirm_bookings(self, request, queryset):
        from django.core.exceptions import ValidationError
        done, failed = 0, []
        for booking in queryset.exclude(status=m.EventRegistration.Status.CONFIRMED):
            booking.status = m.EventRegistration.Status.CONFIRMED
            try:
                booking.full_clean()
                booking.save()
                done += 1
            except ValidationError as exc:
                failed.append(f'{booking.reference}: {"; ".join(exc.messages)}')
        self.message_user(request, f'{done} booking(s) confirmed.' + (f' Not confirmed — {" | ".join(failed)}' if failed else ''))

    @admin.action(description='Cancel selected bookings (releases slots)')
    def cancel_bookings(self, request, queryset):
        n = 0
        for booking in queryset.exclude(status=m.EventRegistration.Status.CANCELLED):
            booking.status = m.EventRegistration.Status.CANCELLED
            booking.save()
            n += 1
        self.message_user(request, f'{n} booking(s) cancelled.')


@admin.register(m.Event)
class EventAdmin(PublishableAdmin):
    list_display = ('slug', 'category', 'price', 'is_featured', 'show_in_popup', 'popup_order', 'status')
    list_filter = ('status', 'is_featured', 'show_in_popup', 'category')
    list_editable = ('show_in_popup', 'popup_order')
    search_fields = ('slug', 'translations__title')
    inlines = [EventTranslationInline, EventScheduleInline, EventHighlightInline, EventFormatDetailInline,
               EventItineraryInline, EventRuleInline, EventFAQInline]


for model in (m.TripCategory, m.TripPricingRule, m.TripItinerary, m.TripThingToBring, m.TripAssignment,
              m.EventItineraryItem, m.EventThingToBring, m.EventInclusion, m.EventExclusion,
              m.EventParticipant, m.EventAttendance):
    admin.site.register(model, type(f'{model.__name__}Admin', (ModelAdmin,), {}))
admin.site.register(m.TripStatusHistory, type('TripStatusHistoryAdmin', (ModelAdmin,), {'has_add_permission': lambda s, r: False}))
