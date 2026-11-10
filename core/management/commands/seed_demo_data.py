"""Fill the portal with demo data: one complete booking (through the real services) plus one clearly-marked row in every empty table.

Every demo row is labelled "Demo" and uses demo phone numbers, so it is easy to recognise and remove.
Idempotent: re-running only fills tables that are still empty. Nothing is sent to customers (no WhatsApp/SMS/email, no gateway calls).
"""
import datetime as dt
import decimal
import uuid
from datetime import timedelta

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import CustomerProfile, User
from admin_api.registry import RESOURCES
from bookings.models import Booking, BookingParticipant, CheckoutOrder
from bookings.services import CheckoutLine, create_checkout
from payments import services as pay
from payments.models import Payment, PaymentKind
from tenancy.context import tenant_scope
from tenancy.models import Tenant, TenantMembership
from trips.models import Trip, TripPickupPoint, TripPolicy, TripSchedule, TripTranslation
from operations.models import PickupLocation

CUSTOMER_PHONE = '+919000000101'
FINANCE_PHONE = '+919000000102'
MAX_DEPTH = 4


class Command(BaseCommand):
    help = 'Seed one complete demo booking and one demo row in every empty admin table.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default='gohyderabad')
        parser.add_argument('--dry-run', action='store_true', help='Run everything, then roll back.')

    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError('Demo data is disabled when DEBUG=False. Use a disposable development or test database.')
        try:
            tenant = Tenant.objects.get(slug=o['tenant'])
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant '{o['tenant']}'.")
        self.stamp = timezone.now()
        self.failures = []
        with tenant_scope(tenant.pk), transaction.atomic():
            self.tenant = tenant
            self.core_flow()
            self.fill_empty_tables()
            empties = [k for k, r in RESOURCES.items() if not self.resource_qs(r).exists()]
            if o['dry_run']:
                transaction.set_rollback(True)
        if self.failures:
            self.stdout.write(self.style.WARNING(f'{len(self.failures)} table(s) could not be filled:'))
            for key, why in self.failures:
                self.stdout.write(f'  - {key}: {why}')
        self.stdout.write(self.style.SUCCESS(f'Done. {len(RESOURCES) - len(empties)} of {len(RESOURCES)} admin tables now have data.'
                                             + (' (dry run: rolled back)' if o['dry_run'] else '')))
        if empties and not o['dry_run']:
            self.stdout.write('Still empty: ' + ', '.join(empties))

    # ---------------------------------------------------------------- the one booking
    def core_flow(self):
        admin = User.objects.filter(is_superuser=True, tenant_memberships__tenant=self.tenant).order_by('pk').first() or User.objects.filter(is_superuser=True).order_by('pk').first()
        if admin is None:
            raise CommandError('Create a superuser first (python manage.py createsuperuser).')

        finance = self.user(FINANCE_PHONE, 'Demo Finance Manager', 'demo.finance@example.com', staff=True)
        finance.groups.add(*Group.objects.filter(name='Finance Manager'))
        customer = self.user(CUSTOMER_PHONE, 'Demo Customer', 'demo.customer@example.com', staff=False)
        CustomerProfile.objects.get_or_create(user=customer, tenant=self.tenant)

        if Booking.objects.filter(primary_booker=customer).exists():
            self.stdout.write('Demo booking already exists, skipping the booking flow.')
            return

        trip, _ = Trip.objects.get_or_create(slug='demo-sunrise-trek', defaults={
            'status': 'DRAFT', 'operational_status': Trip.Operational.OPEN, 'duration_hours': 8, 'difficulty': 'EASY'})
        TripTranslation.objects.get_or_create(trip=trip, language='en', defaults={
            'title': 'Demo Sunrise Trek', 'summary': 'Demo trip created by seed_demo_data.', 'status': 'DRAFT'})
        loc, _ = PickupLocation.objects.get_or_create(name='Demo Pickup: Jubilee Hills Check Post', defaults={
            'address': 'Jubilee Hills, Hyderabad', 'latitude': decimal.Decimal('17.4325'), 'longitude': decimal.Decimal('78.4071')})
        point, _ = TripPickupPoint.objects.get_or_create(trip=trip, name='Jubilee Hills Check Post', defaults={
            'pickup_location': loc, 'address': 'Jubilee Hills, Hyderabad', 'pickup_time': dt.time(5, 30)})
        for days, bp in ((14, 10000), (7, 5000), (2, 0)):
            TripPolicy.objects.get_or_create(trip=trip, days_before=days, defaults={'refund_basis_points': bp, 'note': 'Demo refund tier'})
        starts = (self.stamp + timedelta(days=30)).replace(hour=5, minute=30, second=0, microsecond=0)
        schedule, _ = TripSchedule.objects.get_or_create(trip=trip, starts_at=starts, defaults={
            'ends_at': starts + timedelta(hours=8), 'capacity': 20, 'price_per_participant': decimal.Decimal('999.00')})

        # create_checkout only accepts PUBLISHED trips; publish for the call, then put it back so the live website is unchanged.
        Trip.objects.filter(pk=trip.pk).update(status='PUBLISHED')
        try:
            order = create_checkout(customer, [CheckoutLine(schedule.pk, 2, point.pk)], 'demo-checkout-001')
        finally:
            Trip.objects.filter(pk=trip.pk).update(status='DRAFT')
        booking = order.bookings.first()

        for name, age in (('Demo Customer', 31), ('Demo Companion', 29)):
            BookingParticipant.objects.get_or_create(booking=booking, full_name=name, defaults={
                'age': age, 'phone': CUSTOMER_PHONE, 'emergency_contact_name': 'Demo Contact', 'emergency_contact_phone': FINANCE_PHONE,
                'waiver_accepted_at': self.stamp})

        due = pay.amounts_due(list(order.bookings.all()), PaymentKind.ADVANCE)
        payment = pay.record_manual_payment(admin, order, PaymentKind.ADVANCE, sum(due.values(), decimal.Decimal('0.00')), 'DEMO-UTR-0001')
        pay.verify_manual_payment(finance, payment, True, 'Demo verification')   # a different staff member verifies
        booking.refresh_from_db()
        self.stdout.write(f'Demo booking {booking.reference}: status {booking.status}, total {booking.total_amount}.')

    def user(self, phone, name, email, staff):
        user, created = User.objects.get_or_create(phone_number=phone, defaults={
            'full_name': name, 'email': email, 'kind': User.Kind.ADMIN if staff else User.Kind.CUSTOMER, 'is_staff': staff})
        if created:
            user.set_unusable_password()
            user.save(update_fields=['password'])
        TenantMembership.objects.get_or_create(tenant=self.tenant, user=user, defaults={
            'role': TenantMembership.Role.STAFF if staff else TenantMembership.Role.CUSTOMER})
        return user

    # ---------------------------------------------------------------- every other table
    def count_empty(self):
        with tenant_scope(self.tenant.pk):
            return [k for k, r in RESOURCES.items() if not self.resource_qs(r).exists()]

    @staticmethod
    def resource_qs(resource):
        qs = resource.model._default_manager.all()
        return qs.filter(**resource.queryset_filter) if resource.queryset_filter else qs

    def fill_empty_tables(self):
        for key, resource in RESOURCES.items():
            if self.resource_qs(resource).exists():
                continue
            try:
                with transaction.atomic():
                    self.make(resource.model, 0, dict(resource.queryset_filter))
            except Exception as exc:   # noqa: BLE001 - report and carry on; each table is independent
                self.failures.append((key, f'{type(exc).__name__}: {str(exc)[:160]}'))

    def reuse_or_make(self, model, depth):
        if model is User:
            return User.objects.get(phone_number=CUSTOMER_PHONE)
        existing = model._default_manager.first()
        return existing or self.make(model, depth + 1)

    def make(self, model, depth, overrides=None):
        if depth > MAX_DEPTH:
            raise RecursionError(f'dependency chain too deep at {model.__name__}')
        values = dict(overrides or {})
        for f in model._meta.concrete_fields:
            if f.name in values or f.name == 'tenant' or f.primary_key and (f.has_default() or isinstance(f, models.AutoField)):
                continue
            if f.is_relation and (f.many_to_one or f.one_to_one):
                if f.null or f.blank:
                    continue
                values[f.name] = self.reuse_or_make(f.related_model, depth)
                continue
            required = not (f.null or f.blank or f.has_default() or getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False))
            if not required and f.name not in ('name', 'title', 'label'):
                continue
            if isinstance(f, models.AutoField):
                continue
            values[f.name] = self.value_for(f, model)
        return model._default_manager.create(**values)

    def value_for(self, f, model):
        n = f.name
        tag = uuid.uuid4().hex[:8]
        if model.__name__ == 'NotificationJob' and n == 'status':
            return 'SKIPPED'   # never QUEUED: a worker must not try to message a demo number
        if f.choices:
            return f.choices[0][0]
        if isinstance(f, models.BooleanField):
            return False
        if isinstance(f, models.SlugField):
            return f'demo-{tag}'
        if isinstance(f, models.EmailField):
            return f'demo.{tag}@example.com'
        if isinstance(f, models.URLField):
            return 'https://example.com/demo'
        if isinstance(f, (models.CharField, models.TextField)):
            if 'phone' in n:
                return '+919000000199'
            if 'email' in n:
                return f'demo.{tag}@example.com'
            if n in ('name', 'title', 'label'):
                return f'Demo {model._meta.verbose_name}'[:f.max_length or 200] if isinstance(f, models.CharField) else f'Demo {n}'
            if 'slug' in n:
                return f'demo-{tag}'
            if 'ip' == n:
                return '127.0.0.1'
            text = f'demo-{n}-{tag}' if f.unique else f'Demo {n.replace("_", " ")}'
            return text[:f.max_length] if isinstance(f, models.CharField) and f.max_length else text
        if isinstance(f, models.DecimalField):
            return decimal.Decimal('1.00')
        if isinstance(f, (models.FloatField,)):
            return 1.0
        if isinstance(f, models.IntegerField):
            return 1
        if isinstance(f, models.DateTimeField):
            return self.stamp
        if isinstance(f, models.DateField):
            return self.stamp.date()
        if isinstance(f, models.TimeField):
            return dt.time(9, 0)
        if isinstance(f, models.DurationField):
            return timedelta(hours=1)
        if isinstance(f, models.UUIDField):
            return uuid.uuid4()
        if isinstance(f, models.GenericIPAddressField):
            return '127.0.0.1'
        if isinstance(f, models.JSONField):
            return {}
        if isinstance(f, models.FileField):
            return ContentFile(b'demo', name=f'demo-{tag}.txt')
        raise TypeError(f'no demo value for {model.__name__}.{n} ({type(f).__name__})')
