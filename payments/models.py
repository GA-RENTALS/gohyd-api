"""Payments, refunds, GST, invoices, finance (sections 3.5, 5, 13.5, 13.6)."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TenantBound, Timestamped, UUIDModel

MONEY = dict(max_digits=12, decimal_places=2)


# ---------------- GST (3.5) ----------------
class BusinessEntity(Timestamped):
    """Business GSTIN and legal entity details printed on invoices."""
    legal_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    pan = models.CharField(max_length=10, blank=True)
    address = models.TextField(blank=True)
    state_code = models.CharField(max_length=2, blank=True)
    is_default = models.BooleanField(default=True)

    class Meta:
        db_table = 'business_entities'
        verbose_name_plural = 'business entities'

    def __str__(self):
        return self.legal_name


class GstConfiguration(Timestamped):
    """
    Configurable and versioned: edit by creating a NEW row (set effective_from); bookings/invoices keep a
    snapshot of the values used, so changing settings never recalculates historical invoices.
    """
    name = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True, help_text='Untick for tax-free trips/periods (subject to tax adviser approval).')
    price_includes_tax = models.BooleanField(default=False, help_text='Displayed price is GST-inclusive.')
    rate_basis_points = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10000)], help_text='Total rate, 500 = 5%.')
    components = models.JSONField(default=list, blank=True, help_text='e.g. [{"name":"CGST","bp":250},{"name":"SGST","bp":250}]')
    sac_code = models.CharField(max_length=10, blank=True)
    effective_from = models.DateTimeField()
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = 'gst_configurations'
        ordering = ['-effective_from']

    def snapshot(self):
        return {'id': str(self.pk), 'name': self.name, 'enabled': self.enabled, 'price_includes_tax': self.price_includes_tax,
                'rate_basis_points': self.rate_basis_points, 'components': self.components, 'sac_code': self.sac_code,
                'effective_from': self.effective_from.isoformat()}

    def __str__(self):
        return f'{self.name} ({self.rate_basis_points / 100:g}%)'


# ---------------- Payments (5) ----------------
class PaymentKind(models.TextChoices):
    ADVANCE = 'ADVANCE'
    BALANCE = 'BALANCE'
    FULL = 'FULL'


class Payment(UUIDModel, Timestamped):
    """Gateway or manual transaction. One payment may be allocated across several bookings of a checkout."""
    class Method(models.TextChoices):
        RAZORPAY = 'RAZORPAY'
        MANUAL = 'MANUAL'

    class Status(models.TextChoices):
        CREATED = 'CREATED'
        PENDING_VERIFICATION = 'PENDING_VERIFICATION'   # manual payments await a verifier
        SUCCEEDED = 'SUCCEEDED'
        FAILED = 'FAILED'
        REJECTED = 'REJECTED'

    checkout = models.ForeignKey('bookings.CheckoutOrder', on_delete=models.PROTECT, related_name='payments')
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payments')
    kind = models.CharField(max_length=10, choices=PaymentKind.choices)
    method = models.CharField(max_length=10, choices=Method.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.CREATED, db_index=True)
    currency = models.CharField(max_length=3, default='INR')
    amount = models.DecimalField(validators=[MinValueValidator(0)], **MONEY)
    gateway_order_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    gateway_payment_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    idempotency_key = models.CharField(max_length=80, unique=True)
    gateway_fee = models.DecimalField(default=0, **MONEY)
    manual_reference = models.CharField(max_length=120, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'payments'
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gte=0), name='payment_amount_nonneg')]


class PaymentTransaction(UUIDModel):
    """Append-only history: successful records are never overwritten (5.2)."""
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='transactions')
    event = models.CharField(max_length=60)
    status = models.CharField(max_length=24)
    amount = models.DecimalField(**MONEY)
    raw = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_transactions'
        ordering = ['created_at']


class PaymentAllocation(UUIDModel):
    """How a payment is split across bookings (advance portion and later balance portions)."""
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='allocations')
    booking = models.ForeignKey('bookings.Booking', on_delete=models.PROTECT, related_name='payment_allocations')
    kind = models.CharField(max_length=10, choices=PaymentKind.choices)
    amount = models.DecimalField(validators=[MinValueValidator(0)], **MONEY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_allocations'
        indexes = [models.Index(fields=['booking', 'kind'])]


class PaymentGatewayEvent(UUIDModel):
    """Webhook inbox. UNIQUE(provider, event_id) is the duplicate-webhook protection."""
    provider = models.CharField(max_length=20, default='razorpay')
    event_id = models.CharField(max_length=100)
    event_type = models.CharField(max_length=80)
    payload = models.JSONField()
    signature_valid = models.BooleanField()
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_gateway_events'
        unique_together = ('provider', 'event_id')


class PaymentVerification(UUIDModel):
    """Manual payment verification: who confirmed receipt of what, with proof."""
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='verifications')
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    approved = models.BooleanField()
    note = models.CharField(max_length=255, blank=True)
    proof = models.FileField(upload_to='payment_proofs/%Y/%m/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_verifications'


class Refund(UUIDModel, Timestamped):
    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED'
        APPROVED = 'APPROVED'
        PROCESSING = 'PROCESSING'
        PROCESSED = 'PROCESSED'
        FAILED = 'FAILED'
        REJECTED = 'REJECTED'

    booking = models.ForeignKey('bookings.Booking', on_delete=models.PROTECT, related_name='refunds')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    currency = models.CharField(max_length=3, default='INR')
    amount = models.DecimalField(validators=[MinValueValidator(0)], **MONEY)
    tax_adjustment = models.DecimalField(default=0, help_text='GST portion reversed (for the credit note).', **MONEY)
    reason = models.CharField(max_length=255, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'refunds'
        ordering = ['-created_at']


class EventRefund(UUIDModel, Timestamped):
    """Money owed back on a cancelled, paid event booking. Event fees are paid by UPI outside the system, so staff send
    the refund by hand and record it here; recording it as sent tells the customer on WhatsApp."""

    class Status(models.TextChoices):
        DUE = 'DUE', 'To send'
        SENT = 'SENT', 'Sent'
        NOT_REFUNDED = 'NOT_REFUNDED', 'Not refunded'

    registration = models.OneToOneField('trips.EventRegistration', on_delete=models.PROTECT, related_name='refund')
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.DUE, db_index=True)
    amount = models.DecimalField(validators=[MinValueValidator(0)], help_text='Due when opened; what was actually sent once recorded.', **MONEY)
    refund_basis_points = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10000)], editable=False)
    upi_reference = models.CharField('UPI transaction ID', max_length=40, blank=True)
    note = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    recorded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'event_refunds'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.registration.reference} · ₹{self.amount} · {self.get_status_display()}'


class RefundTransaction(UUIDModel):
    """Refunds are separate transactions, never edits of the original payment."""
    refund = models.ForeignKey(Refund, on_delete=models.PROTECT, related_name='transactions')
    payment = models.ForeignKey(Payment, null=True, on_delete=models.PROTECT, related_name='refund_transactions')
    gateway_refund_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    status = models.CharField(max_length=12)
    amount = models.DecimalField(**MONEY)
    raw = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'refund_transactions'


class PaymentReconciliationRecord(UUIDModel):
    """Internal records vs gateway settlements."""
    payment = models.ForeignKey(Payment, null=True, on_delete=models.SET_NULL, related_name='reconciliations')
    settlement = models.ForeignKey('Settlement', null=True, blank=True, on_delete=models.SET_NULL, related_name='records')
    gateway_amount = models.DecimalField(null=True, **MONEY)
    internal_amount = models.DecimalField(null=True, **MONEY)
    matched = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_reconciliation_records'


# ---------------- Invoices (3.5) ----------------
class InvoiceSequence(TenantBound):
    """One row per (series, financial year); incremented under row lock so numbers are gapless."""
    series = models.CharField(max_length=20, primary_key=True)  # e.g. INV-2026-27, CN-2026-27
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'invoice_sequences'


class Invoice(UUIDModel):
    number = models.CharField(max_length=30, unique=True)
    booking = models.ForeignKey('bookings.Booking', on_delete=models.PROTECT, related_name='invoices')
    entity = models.ForeignKey(BusinessEntity, on_delete=models.PROTECT, related_name='invoices')
    entity_snapshot = models.JSONField()
    billing_name = models.CharField(max_length=200, blank=True)
    billing_gstin = models.CharField(max_length=15, blank=True)
    billing_address = models.TextField(blank=True)
    currency = models.CharField(max_length=3, default='INR')
    subtotal = models.DecimalField(**MONEY)
    tax_amount = models.DecimalField(**MONEY)
    total = models.DecimalField(**MONEY)
    tax_snapshot = models.JSONField()
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'invoices'
        ordering = ['-issued_at']


class InvoiceItem(TenantBound):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    unit_amount = models.DecimalField(**MONEY)
    tax_amount = models.DecimalField(**MONEY)
    total = models.DecimalField(**MONEY)

    class Meta:
        db_table = 'invoice_items'


class CreditNote(UUIDModel):
    number = models.CharField(max_length=30, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='credit_notes')
    refund = models.OneToOneField(Refund, null=True, blank=True, on_delete=models.PROTECT, related_name='credit_note')
    amount = models.DecimalField(**MONEY)
    tax_amount = models.DecimalField(**MONEY)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'credit_notes'


# ---------------- Finance (13.6) ----------------
class ExpenseCategory(TenantBound):
    name = models.CharField(max_length=100, unique=True)   # transport, accommodation, vendor, marketing, gateway fees ...

    class Meta:
        db_table = 'expense_categories'
        verbose_name_plural = 'expense categories'

    def __str__(self):
        return self.name


class Expense(UUIDModel, Timestamped):
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(validators=[MinValueValidator(0)], **MONEY)
    incurred_on = models.DateField()
    vendor = models.ForeignKey('operations.Vendor', null=True, blank=True, on_delete=models.SET_NULL, related_name='expenses')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'expenses'
        ordering = ['-incurred_on']


class TripExpense(TenantBound):
    """Allocates an expense to a trip departure for trip-wise profitability."""
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='trip_links')
    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.PROTECT, related_name='expenses')
    amount = models.DecimalField(**MONEY)

    class Meta:
        db_table = 'trip_expenses'


class VendorInvoice(UUIDModel, Timestamped):
    vendor = models.ForeignKey('operations.Vendor', on_delete=models.PROTECT, related_name='invoices')
    number = models.CharField(max_length=60)
    amount = models.DecimalField(**MONEY)
    tax_amount = models.DecimalField(default=0, **MONEY)
    due_on = models.DateField(null=True, blank=True)
    document = models.FileField(upload_to='vendor_invoices/%Y/%m/', blank=True)

    class Meta:
        db_table = 'vendor_invoices'
        unique_together = ('vendor', 'number')


class VendorPayment(UUIDModel, Timestamped):
    invoice = models.ForeignKey(VendorInvoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(validators=[MinValueValidator(0)], **MONEY)
    paid_on = models.DateField()
    reference = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = 'vendor_payments'


class Settlement(UUIDModel):
    """A gateway payout (Razorpay settlement) to reconcile against."""
    provider = models.CharField(max_length=20, default='razorpay')
    provider_settlement_id = models.CharField(max_length=80, unique=True)
    amount = models.DecimalField(**MONEY)
    fees = models.DecimalField(default=0, **MONEY)
    settled_on = models.DateField()

    class Meta:
        db_table = 'settlements'


class FinancialPeriod(TenantBound):
    name = models.CharField(max_length=40, unique=True)   # FY 2026-27 Q1
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        db_table = 'financial_periods'


class FinancialAdjustment(UUIDModel, Timestamped):
    period = models.ForeignKey(FinancialPeriod, on_delete=models.PROTECT, related_name='adjustments')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(**MONEY)   # signed
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'financial_adjustments'
