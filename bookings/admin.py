from django.contrib import admin, messages
from unfold.admin import ModelAdmin, TabularInline

from core.admin import ReadOnlyAdmin, register_remaining
from . import models as m
from .services import BookingError, cancel_booking, grant_departure_exception, outstanding, paid_amount


class ParticipantInline(TabularInline):
    model = m.BookingParticipant
    extra = 0


class HistoryInline(TabularInline):
    model = m.BookingStatusHistory
    extra = 0
    readonly_fields = ('from_status', 'to_status', 'actor', 'note', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None): return False


@admin.register(m.Booking)
class BookingAdmin(ModelAdmin):
    list_display = ('reference', 'primary_booker', 'schedule', 'status', 'total_amount', 'paid', 'outstanding_amt', 'balance_due_at')
    list_filter = ('status', 'schedule__trip')
    search_fields = ('reference', 'primary_booker__phone_number', 'primary_booker__full_name')
    date_hierarchy = 'created_at'
    inlines = [ParticipantInline, HistoryInline]
    readonly_fields = ('reference', 'checkout', 'checkout_item', 'primary_booker', 'schedule', 'participant_count', 'currency', 'unit_price', 'subtotal',
                       'tax_amount', 'total_amount', 'advance_basis_points', 'advance_amount', 'balance_amount', 'balance_due_at', 'tax_snapshot',
                       'refund_policy_snapshot', 'status')
    actions = ['cancel_selected', 'grant_exception']

    @admin.display(description='Paid')
    def paid(self, o): return paid_amount(o)

    @admin.display(description='Outstanding')
    def outstanding_amt(self, o): return outstanding(o)

    @admin.action(description='Cancel selected bookings (refund per policy)')
    def cancel_selected(self, request, qs):
        for b in qs:
            try:
                cancel_booking(b, request.user, 'Cancelled by staff', request)
            except BookingError as e:
                self.message_user(request, f'{b.reference}: {e.message}', messages.ERROR)

    @admin.action(description='Clear for departure despite unpaid balance (audited; needs permission)')
    def grant_exception(self, request, qs):
        for b in qs:
            try:
                grant_departure_exception(b, request.user, 'Granted from admin', request)
            except BookingError as e:
                self.message_user(request, f'{b.reference}: {e.message}', messages.ERROR)


@admin.register(m.CheckoutOrder)
class CheckoutAdmin(ReadOnlyAdmin):
    list_display = ('reference', 'user', 'status', 'total_amount', 'advance_total', 'created_at')
    list_filter = ('status',)
    search_fields = ('reference', 'user__phone_number')


register_remaining('bookings', readonly=('BookingStatusHistory', 'BookingSeatAllocation'))
