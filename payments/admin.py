from django.contrib import admin, messages
from unfold.admin import ModelAdmin, TabularInline

from bookings.services import BookingError
from core.admin import ReadOnlyAdmin, register_remaining
from . import models as m
from . import services


class TxnInline(TabularInline):
    model = m.PaymentTransaction
    extra = 0
    readonly_fields = ('event', 'status', 'amount', 'raw', 'created_at')
    can_delete = False
    def has_add_permission(self, request, obj=None): return False


class AllocInline(TabularInline):
    model = m.PaymentAllocation
    extra = 0
    readonly_fields = ('booking', 'kind', 'amount')
    can_delete = False
    def has_add_permission(self, request, obj=None): return False


@admin.register(m.Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'checkout', 'payer', 'kind', 'method', 'status', 'amount', 'gateway_payment_id')
    list_filter = ('status', 'method', 'kind')
    search_fields = ('gateway_payment_id', 'gateway_order_id', 'checkout__reference', 'payer__phone_number')
    inlines = [AllocInline, TxnInline]
    actions = ['verify_manual', 'reject_manual']

    @admin.action(description='Verify selected manual payments (a different person than the one who entered them)')
    def verify_manual(self, request, qs):
        for p in qs:
            try:
                services.verify_manual_payment(request.user, p, True, request=request)
            except BookingError as e:
                self.message_user(request, f'{p.pk}: {e.message}', messages.ERROR)

    @admin.action(description='Reject selected manual payments')
    def reject_manual(self, request, qs):
        for p in qs:
            try:
                services.verify_manual_payment(request.user, p, False, request=request)
            except BookingError as e:
                self.message_user(request, f'{p.pk}: {e.message}', messages.ERROR)


@admin.register(m.Refund)
class RefundAdmin(ModelAdmin):
    list_display = ('created_at', 'booking', 'amount', 'status', 'reason')
    list_filter = ('status',)
    actions = ['approve']

    @admin.action(description='Approve selected refunds (queues gateway processing)')
    def approve(self, request, qs):
        for r in qs:
            try:
                services.approve_refund(request.user, r, request)
            except BookingError as e:
                self.message_user(request, f'{r.pk}: {e.message}', messages.ERROR)


@admin.register(m.GstConfiguration)
class GstAdmin(ModelAdmin):
    list_display = ('name', 'enabled', 'price_includes_tax', 'rate_basis_points', 'effective_from', 'is_default')
    help_text = 'To change rates, add a NEW configuration with a later effective date. Existing invoices keep their snapshot.'


register_remaining('payments', readonly=('PaymentTransaction', 'PaymentAllocation', 'PaymentGatewayEvent', 'RefundTransaction', 'Invoice', 'InvoiceItem',
                                          'InvoiceSequence', 'CreditNote', 'PaymentVerification'))
