"""Idempotent first-run data: roles, settings, GST default, business entity, KPI/event definitions, notification templates."""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Setting

# role -> {app_label: actions}; actions: view/add/change/delete (+ custom perms by codename)
ALL = ('view', 'add', 'change', 'delete')
RW = ('view', 'add', 'change')
RO = ('view',)
ROLES = {
    'Super Admin': '*',
    'Admin': '*',
    'Content Manager': {'content': ALL, 'trips': RO},
    'Content Writer': {'content': RW},
    'Trip Manager': {'trips': ALL, 'content': RW, 'bookings': RO, 'operations': RW},
    'Trip Organizer': {'trips': RO, 'bookings': ('view', 'change'), 'operations': ('view', 'change')},
    'Booking Manager': {'bookings': ALL, 'accounts': RO, 'trips': RO, 'payments': RO},
    'Finance Manager': {'payments': ALL, 'bookings': RO, 'tracking': RO},
    'Customer Support': {'crm': RW, 'bookings': ('view', 'change'), 'accounts': RO, 'payments': RO},
    'Marketing Manager': {'crm': ALL, 'tracking': RO, 'notifications': RW},
    'Operations Manager': {'operations': ALL, 'bookings': RO, 'trips': RO},
    'Analytics Viewer': {'tracking': RO, 'payments': RO, 'bookings': RO},
}
EXTRA = {   # custom permissions (approval / financial / export / exception)
    'Booking Manager': ['bookings.grant_departure_exception'],
    'Super Admin': ['bookings.grant_departure_exception'],
    'Admin': ['bookings.grant_departure_exception'],
}

KPIS = [
    ('gross_booking_value', 'Gross booking value', 'Total value of bookings created in the period (incl. GST), before cancellations.', 'SUM(bookings.total_amount) for bookings with created_at in range.'),
    ('recognized_revenue', 'Recognized revenue', 'Revenue for trips that have departed, net of refunds and GST.', 'SUM(subtotal) for bookings whose trip schedule started in range, minus refunds processed for them.'),
    ('collections', 'Cash collections', 'Money actually received.', 'SUM(payments.amount) with status SUCCEEDED in range, minus refund transactions processed.'),
    ('outstanding_balance', 'Outstanding balance', 'Total unpaid on non-cancelled bookings.', 'SUM(total_amount - paid) over bookings not cancelled.'),
    ('occupancy', 'Occupancy', 'Seats sold over capacity.', 'seats_booked / capacity per schedule.'),
    ('cac', 'Customer acquisition cost', 'Marketing spend per new customer.', 'campaign_costs in range / new customers with a first booking in range.'),
]
EVENTS = ['page_view', 'search_performed', 'category_viewed', 'destination_viewed', 'trip_viewed', 'trip_shared', 'trip_saved', 'registration_started',
          'registration_completed', 'booking_started', 'participant_added', 'pickup_selected', 'payment_started', 'payment_succeeded', 'booking_confirmed',
          'booking_cancelled', 'membership_viewed', 'membership_purchased', 'enquiry_submitted', 'review_submitted']


class Command(BaseCommand):
    help = 'Seed roles, default settings and reference data (safe to re-run).'

    def handle(self, *a, **k):
        from django.conf import settings
        from notifications.models import Channel, NotificationEvent, NotificationTemplate
        from payments.models import BusinessEntity, GstConfiguration
        from tracking.models import AnalyticsEventDefinition, KpiDefinition

        perms = {(p.content_type.app_label, p.codename): p for p in Permission.objects.select_related('content_type')}
        for role, spec in ROLES.items():
            g, _ = Group.objects.get_or_create(name=role)
            if spec == '*':
                chosen = [p for (app, _), p in perms.items() if app in {'content', 'trips', 'bookings', 'payments', 'operations', 'crm', 'tracking', 'notifications', 'accounts', 'core'}]
            else:
                chosen = [p for (app, code), p in perms.items() if app in spec and code.split('_')[0] in spec[app]]
            for full in EXTRA.get(role, []):
                app, code = full.split('.')
                chosen.append(perms[(app, code)])
            g.permissions.set(chosen)

        Setting.objects.get_or_create(key='advance.default_basis_points', defaults={'value': settings.DEFAULT_ADVANCE_BASIS_POINTS,
                                      'description': 'Default advance % in basis points (3000 = 30%). PLACEHOLDER: set the real business value.'})
        Setting.objects.get_or_create(key='balance.default_due_days_before', defaults={'value': settings.DEFAULT_BALANCE_DUE_DAYS_BEFORE,
                                      'description': 'Balance due this many days before departure. PLACEHOLDER: set the real business value.'})
        BusinessEntity.objects.get_or_create(legal_name='GoHyderabad (set legal name)', defaults={'is_default': True})
        GstConfiguration.objects.get_or_create(name='GST (placeholder, needs tax adviser sign-off)', defaults=dict(
            enabled=False, rate_basis_points=0, effective_from=timezone.now(), is_default=True))
        for key, name, d, c in KPIS:
            KpiDefinition.objects.get_or_create(key=key, defaults={'name': name, 'definition': d, 'calculation': c})
        for e in EVENTS:
            AnalyticsEventDefinition.objects.get_or_create(name=e)
        for ev in NotificationEvent.values:
            for ch in (Channel.WHATSAPP, Channel.EMAIL, Channel.SMS, Channel.IN_APP):
                NotificationTemplate.objects.get_or_create(event=ev, channel=ch)
        self.stdout.write(self.style.SUCCESS('Seeded roles, settings and reference data.'))
