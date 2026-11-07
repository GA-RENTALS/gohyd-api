import json
import os
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.core.exceptions import RequestDataTooBig
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.http import Http404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import ResourceAssignment, User
from bookings.models import Booking, BookingParticipant, CheckoutOrder
from bookings.services import BookingError, grant_departure_exception
from core.models import AuditLog, DataAccessLog
from core.security import get_client_ip
from django.conf import settings
from core.models import Setting
from payments.models import BusinessEntity, GstConfiguration, Payment, PaymentKind, Refund
from payments import services as payment_services
from content.models import ContentStatus
from trips.models import Trip

from .permissions import StaffOnly, has_staff_membership
from .registry import MODULE_LABELS, RESOURCES, Resource, get_resource, module_resource_keys
from .serializers import MAX_UPLOAD_MB, resource_serializer, schema_for


class AdminPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _permission_name(resource, action='view'):
    model = resource.model
    return f'{model._meta.app_label}.{action}_{model._meta.model_name}'


def _can(user, resource, action='view'):
    return bool(user.is_authenticated and user.is_staff and user.has_perm(_permission_name(resource, action)))


def _write_mode_allows(resource, action):
    if action == 'view':
        return True
    if action == 'add':
        return resource.mode in {'full', 'create'}
    if action == 'change':
        return resource.mode in {'full', 'update'}
    if action == 'delete':
        return resource.mode == 'full'
    return False


def _queryset(resource, user, tenant):
    qs = resource.model._default_manager.all()
    if resource.model is User:
        if tenant is None:
            return qs.none()
        qs = qs.filter(tenant_memberships__tenant=tenant, tenant_memberships__is_active=True)
    if resource.queryset_filter:
        qs = qs.filter(**resource.queryset_filter)
    return qs


def _serialize(resource, instance, request=None):
    return resource_serializer(resource)(instance, context={'request': request}).data


def _request_meta(request):
    return get_client_ip(request), request.META.get('HTTP_USER_AGENT', '')[:300]


def _plain(value):
    """JSON-safe copy (UUIDs, Decimals and datetimes in serializer output aren't accepted by JSONField)."""
    return None if value is None else json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _audit(request, action, resource, instance, before=None, after=None):
    before, after = _plain(before), _plain(after)
    ip, user_agent = _request_meta(request)
    AuditLog.objects.create(
        actor=request.user,
        action=action,
        entity_type=resource.model._meta.label_lower,
        entity_id=str(instance.pk),
        before=before,
        after=after,
        ip=ip,
        user_agent=user_agent,
    )


def _access_log(request, resource, instance=None, purpose='staff admin view'):
    if not resource.personal_data:
        return
    DataAccessLog.objects.create(
        actor=request.user,
        entity_type=resource.model._meta.label_lower,
        entity_id=str(instance.pk) if instance is not None else '',
        purpose=purpose[:200],
    )


def _resolve(resource_key):
    resource = get_resource(resource_key)
    if not resource:
        raise Http404('Unknown staff resource.')
    return resource


def _require_model_permission(request, resource, action='view'):
    if not has_staff_membership(request):
        raise PermissionDenied('Staff access is required.')
    if resource.key == 'staff-groups' and not request.user.is_superuser:
        raise PermissionDenied('Permission groups are managed by platform administrators.')
    if not _write_mode_allows(resource, action):
        raise PermissionDenied('This record type is read-only for this action.')
    if not _can(request.user, resource, action):
        raise PermissionDenied('You do not have permission to perform this action.')


def _filter_queryset(request, resource, qs):
    model_fields = {field.name for field in resource.model._meta.fields}
    reserved = {'page', 'page_size', 'search', 'ordering', 'format'}
    for key, value in request.query_params.items():
        if key in reserved or key not in model_fields or not value:
            continue
        qs = qs.filter(**{key: value})
    search = request.query_params.get('search', '').strip()
    if search and resource.search_fields:
        condition = Q()
        for field in resource.search_fields:
            condition |= Q(**{f'{field}__icontains': search})
        qs = qs.filter(condition)
    ordering = request.query_params.get('ordering', '')
    allowed_ordering = set(resource.ordering_fields)
    if ordering:
        pieces = [piece.strip() for piece in ordering.split(',') if piece.strip()]
        valid = [piece for piece in pieces if piece.lstrip('-') in allowed_ordering]
        if valid:
            qs = qs.order_by(*valid)
    if not qs.ordered:   # stable pagination for tables without a default ordering
        qs = qs.order_by('-created_at' if 'created_at' in model_fields else 'pk')
    return qs.distinct()


class UploadAwareView(APIView):
    """Accepts JSON and multipart (file uploads) and answers an oversized upload with JSON, not an HTML error page."""
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def handle_exception(self, exc):
        if isinstance(exc, RequestDataTooBig):
            return Response({'detail': f'The file is too large (maximum {MAX_UPLOAD_MB} MB).'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        return super().handle_exception(exc)


def _storage_error(exc):
    """File storage (S3/disk) failed while saving an upload. Say so plainly instead of a bare 500."""
    return Response({'detail': 'The file could not be saved. Check that file storage is reachable and configured '
                               f'({type(exc).__name__}).'}, status=status.HTTP_502_BAD_GATEWAY)


def _is_storage_error(exc):
    try:
        from botocore.exceptions import BotoCoreError, ClientError
        return isinstance(exc, (BotoCoreError, ClientError, OSError))
    except ImportError:
        return isinstance(exc, OSError)


def _serializer_error(exc):
    return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)


class AdminSessionView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request):
        return Response({
            'id': request.user.pk,
            'name': request.user.full_name or request.user.phone_number,
            'phone_number': request.user.phone_number,
            'email': request.user.email,
            'permissions': sorted(request.user.get_all_permissions()),
        })


class AdminModuleCatalogView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request):
        modules = []
        for key, label in MODULE_LABELS.items():
            resources = []
            for resource_key in module_resource_keys(key):
                resource = RESOURCES[resource_key]
                actions = {
                    'view': _can(request.user, resource, 'view'),
                    'create': _write_mode_allows(resource, 'add') and _can(request.user, resource, 'add'),
                    'update': _write_mode_allows(resource, 'change') and _can(request.user, resource, 'change'),
                    'delete': _write_mode_allows(resource, 'delete') and _can(request.user, resource, 'delete'),
                }
                if actions['view']:
                    resources.append({'key': resource.key, 'label': resource.label, 'actions': actions})
            if resources or key == 'dashboard':
                modules.append({'key': key, 'label': label, 'resources': resources})
        return Response({'modules': modules})


class AdminResourceSchemaView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request, resource_key):
        resource = _resolve(resource_key)
        _require_model_permission(request, resource, 'view')
        value = schema_for(resource, request)
        value['actions'] = {
            'create': _write_mode_allows(resource, 'add') and _can(request.user, resource, 'add'),
            'update': _write_mode_allows(resource, 'change') and _can(request.user, resource, 'change'),
            'delete': _write_mode_allows(resource, 'delete') and _can(request.user, resource, 'delete'),
        }
        value['searchable'] = list(resource.search_fields)
        value['ordering'] = list(resource.ordering_fields)
        return Response(value)


class AdminResourceCollectionView(UploadAwareView):
    permission_classes = [StaffOnly]
    paginator = AdminPagination()

    def get(self, request, resource_key):
        resource = _resolve(resource_key)
        _require_model_permission(request, resource, 'view')
        qs = _filter_queryset(request, resource, _queryset(resource, request.user, request.tenant))
        page = self.paginator.paginate_queryset(qs, request, view=self)
        _access_log(request, resource, purpose='staff list view')
        data = resource_serializer(resource)(page, many=True, context={'request': request}).data
        return self.paginator.get_paginated_response(data)

    def post(self, request, resource_key):
        resource = _resolve(resource_key)
        _require_model_permission(request, resource, 'add')
        serializer = resource_serializer(resource)(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                instance = serializer.save()
                after = _serialize(resource, instance, request)
                _audit(request, f'{resource.key}.create', resource, instance, after=after)
        except IntegrityError as exc:
            return _serializer_error(exc)
        except Exception as exc:   # noqa: BLE001
            if _is_storage_error(exc):
                return _storage_error(exc)
            raise
        return Response(after, status=status.HTTP_201_CREATED)


class AdminResourceDetailView(UploadAwareView):
    permission_classes = [StaffOnly]

    def _get(self, request, resource_key, pk, action='view'):
        resource = _resolve(resource_key)
        _require_model_permission(request, resource, action)
        try:
            instance = _queryset(resource, request.user, request.tenant).get(pk=pk)
        except (ObjectDoesNotExist, ValueError, TypeError):
            raise Http404('Record not found.')
        return resource, instance

    def get(self, request, resource_key, pk):
        resource, instance = self._get(request, resource_key, pk)
        _access_log(request, resource, instance)
        return Response(_serialize(resource, instance, request))

    def put(self, request, resource_key, pk):
        return self._update(request, resource_key, pk, partial=False)

    def patch(self, request, resource_key, pk):
        return self._update(request, resource_key, pk, partial=True)

    def _update(self, request, resource_key, pk, partial):
        resource, instance = self._get(request, resource_key, pk, 'change')
        before = _serialize(resource, instance, request)
        serializer = resource_serializer(resource)(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                instance = serializer.save()
                if resource.key == 'settings' and 'value' in serializer.validated_data and 'PLACEHOLDER' in (instance.description or ''):
                    # a person has now set the real value, so drop the "placeholder" note from its description
                    instance.description = instance.description.split(' PLACEHOLDER')[0].rstrip('. ') + '.'
                    instance.save(update_fields=['description', 'updated_at'])
                after = _serialize(resource, instance, request)
                _audit(request, f'{resource.key}.update', resource, instance, before=before, after=after)
        except IntegrityError as exc:
            return _serializer_error(exc)
        except Exception as exc:   # noqa: BLE001
            if _is_storage_error(exc):
                return _storage_error(exc)
            raise
        return Response(after)

    def delete(self, request, resource_key, pk):
        resource, instance = self._get(request, resource_key, pk, 'delete')
        before = _serialize(resource, instance, request)
        try:
            with transaction.atomic():
                instance.delete()
                _audit(request, f'{resource.key}.delete', resource, instance, before=before)
        except IntegrityError as exc:
            return _serializer_error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffActionView(APIView):
    permission_classes = [StaffOnly]

    def post(self, request, action):
        try:
            if action == 'verify-payment':
                return self._verify_payment(request)
            if action == 'approve-refund':
                return self._approve_refund(request)
            if action == 'record-manual-payment':
                return self._record_manual_payment(request)
            if action == 'departure-exception':
                return self._departure_exception(request)
            if action == 'content-transition':
                return self._content_transition(request)
            if action == 'participant-check-in':
                return self._participant_check_in(request)
        except (BookingError, DjangoValidationError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as exc:
            return _serializer_error(exc)
        except ObjectDoesNotExist:
            raise Http404('Record not found.')
        return Response({'detail': 'Unknown staff action.'}, status=status.HTTP_404_NOT_FOUND)

    def _verify_payment(self, request):
        resource = _resolve('payments')
        _require_model_permission(request, resource, 'change')
        payment = Payment.objects.get(pk=request.data.get('payment_id'))
        payment_services.verify_manual_payment(request.user, payment, bool(request.data.get('approved')), str(request.data.get('note', '')), request)
        _audit(request, 'payments.verify', resource, payment, after=_serialize(resource, payment, request))
        return Response(_serialize(resource, payment, request))

    def _approve_refund(self, request):
        resource = _resolve('refunds')
        if not request.user.has_perm(_permission_name(resource, 'change')):
            raise PermissionDenied('You do not have permission to approve refunds.')
        refund = Refund.objects.get(pk=request.data.get('refund_id'))
        before = _serialize(resource, refund, request)
        payment_services.approve_refund(request.user, refund, request)
        _audit(request, 'refunds.approve', resource, refund, before=before, after=_serialize(resource, refund, request))
        return Response(_serialize(resource, refund, request))

    def _record_manual_payment(self, request):
        resource = _resolve('payments')
        if not request.user.has_perm(_permission_name(resource, 'add')):
            raise PermissionDenied('You do not have permission to record payments.')
        try:
            checkout = CheckoutOrder.objects.get(pk=request.data.get('checkout_id'))
            amount = Decimal(str(request.data.get('amount', '')))
            kind = PaymentKind(request.data.get('kind'))
        except (CheckoutOrder.DoesNotExist, ValueError, TypeError):
            raise serializers.ValidationError({'detail': 'Provide a valid checkout, payment kind, and amount.'})
        payment = payment_services.record_manual_payment(
            request.user, checkout, kind, amount, str(request.data.get('reference', '')),
            booking_ids=request.data.get('booking_ids'), request=request,
        )
        _audit(request, 'payments.manual_record', resource, payment, after=_serialize(resource, payment, request))
        return Response(_serialize(resource, payment, request), status=status.HTTP_201_CREATED)

    def _departure_exception(self, request):
        booking_resource = _resolve('bookings')
        _require_model_permission(request, booking_resource, 'view')
        booking = Booking.objects.get(pk=request.data.get('booking_id'))
        before = _serialize(booking_resource, booking, request)
        booking = grant_departure_exception(booking, request.user, str(request.data.get('reason', '')), request=request)
        _audit(request, 'bookings.departure_exception', booking_resource, booking, before=before, after=_serialize(booking_resource, booking, request))
        return Response(_serialize(booking_resource, booking, request))

    def _content_transition(self, request):
        resource = _resolve(str(request.data.get('resource', '')))
        _require_model_permission(request, resource, 'change')
        instance = resource.model._default_manager.get(pk=request.data.get('id'))
        if not hasattr(instance, 'move_to') and not hasattr(instance, 'publish'):
            raise serializers.ValidationError({'resource': 'This record does not support a publishing workflow.'})
        before = _serialize(resource, instance, request)
        new_status = str(request.data.get('status', '')).upper()
        note = str(request.data.get('note', ''))[:2000]
        if hasattr(instance, 'move_to'):
            instance.move_to(new_status, user=request.user, note=note)
        elif new_status == 'PUBLISHED':
            instance.publish()
        elif new_status == 'SCHEDULED':
            from django.utils.dateparse import parse_datetime
            when = parse_datetime(str(request.data.get('publish_at', '')))
            if not when:
                raise serializers.ValidationError({'publish_at': 'Enter a valid scheduled publication time.'})
            instance.publish(when=when)
        else:
            from content.models import TRANSITIONS
            if new_status not in TRANSITIONS.get(instance.status, set()):
                raise serializers.ValidationError({'status': f'Cannot move from {instance.status} to {new_status}.'})
            instance.status = new_status
            instance.save(update_fields=['status', 'updated_at'])
        _audit(request, f'{resource.key}.workflow', resource, instance, before=before, after=_serialize(resource, instance, request))
        return Response(_serialize(resource, instance, request))

    def _participant_check_in(self, request):
        resource = _resolve('participants')
        _require_model_permission(request, resource, 'change')
        participant = BookingParticipant.objects.get(pk=request.data.get('participant_id'))
        before = _serialize(resource, participant, request)
        participant.checked_in_at = timezone.now()
        participant.save(update_fields=['checked_in_at', 'updated_at'])
        _audit(request, 'participants.check_in', resource, participant, before=before, after=_serialize(resource, participant, request))
        return Response(_serialize(resource, participant, request))


class AdminDashboardView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request):
        today = timezone.localdate()
        start = today - timedelta(days=6)
        cards = []
        now = timezone.now()
        w_cur, w_prev = now - timedelta(days=30), now - timedelta(days=60)

        def delta(model, field='created_at', agg=None, **flt):
            """% change of the last 30 days against the 30 days before (None when there's no baseline)."""
            qs = model.objects.filter(**flt)
            def total(lo, hi):
                part = qs.filter(**{f'{field}__gte': lo, f'{field}__lt': hi})
                return float(part.aggregate(v=Sum(agg))['v'] or 0) if agg else part.count()
            cur, prev = total(w_cur, now), total(w_prev, w_cur)
            return round((cur - prev) / prev * 100, 1) if prev else None

        if request.user.has_perm('trips.view_trip'):
            cards.append({'key': 'trips', 'label': 'Published trips', 'value': Trip.objects.filter(status=ContentStatus.PUBLISHED).count(), 'delta': delta(Trip, status=ContentStatus.PUBLISHED)})
        if request.user.has_perm('bookings.view_booking'):
            cards.append({'key': 'bookings', 'label': 'Bookings', 'value': Booking.objects.exclude(status=Booking.Status.CANCELLED).count(), 'delta': delta(Booking)})
        if request.user.has_perm('payments.view_payment'):
            payments_total = Payment.objects.filter(status=Payment.Status.SUCCEEDED).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            cards.append({'key': 'revenue', 'label': 'Collected', 'value': str(payments_total), 'delta': delta(Payment, agg='amount', status=Payment.Status.SUCCEEDED)})
            cards.append({'key': 'pending-verification', 'label': 'Awaiting verification', 'value': Payment.objects.filter(status=Payment.Status.PENDING_VERIFICATION).count(), 'delta': None})
        if request.user.has_perm('accounts.view_user'):
            customers = User.objects.filter(
                kind=User.Kind.CUSTOMER, is_active=True, tenant_memberships__tenant=request.tenant,
                tenant_memberships__is_active=True)
            cards.append({'key': 'customers', 'label': 'Customers', 'value': customers.count(), 'delta': delta(User, field='date_joined', kind=User.Kind.CUSTOMER, is_active=True,
                                                                                                               tenant_memberships__tenant=request.tenant, tenant_memberships__is_active=True)})

        charts = {}
        if request.user.has_perm('bookings.view_booking'):
            rows = Booking.objects.filter(created_at__date__gte=start).annotate(day=TruncDate('created_at')).values('day').annotate(value=Count('id')).order_by('day')
            charts['bookings'] = self._fill_days(start, today, rows)
        if request.user.has_perm('payments.view_payment'):
            rows = Payment.objects.filter(status=Payment.Status.SUCCEEDED, created_at__date__gte=start).annotate(day=TruncDate('created_at')).values('day').annotate(value=Sum('amount')).order_by('day')
            charts['revenue'] = self._fill_days(start, today, rows)

        year = today.year
        def monthly(qs, field, agg=None):
            """Twelve calendar months: this year against the same month last year."""
            rows = qs.filter(**{f'{field}__year__in': [year, year - 1]}).annotate(m=TruncMonth(field)).values('m').annotate(v=Sum(agg) if agg else Count('id'))
            by = {(r['m'].year, r['m'].month): float(r['v'] or 0) for r in rows}
            labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            return [{'label': labels[i], 'current': by.get((year, i + 1), 0), 'previous': by.get((year - 1, i + 1), 0)} for i in range(12)]
        if request.user.has_perm('bookings.view_booking'):
            charts['bookings_monthly'] = monthly(Booking.objects.exclude(status=Booking.Status.CANCELLED), 'created_at')
        if request.user.has_perm('payments.view_payment'):
            charts['revenue_monthly'] = monthly(Payment.objects.filter(status=Payment.Status.SUCCEEDED), 'created_at', 'amount')

        recent = []
        if request.user.has_perm('bookings.view_booking'):
            recent = list(Booking.objects.select_related('primary_booker', 'schedule__trip').order_by('-created_at').values(
                'id', 'reference', 'status', 'total_amount', 'created_at', 'primary_booker__full_name', 'schedule__trip__slug')[:6])
            for row in recent:
                row['id'] = str(row['id'])
                row['total_amount'] = str(row['total_amount'])
                row['created_at'] = row['created_at'].isoformat()

        return Response({'cards': cards, 'charts': charts, 'recent_bookings': recent, 'setup': self._setup(request.user), 'as_of': timezone.now().isoformat()})

    @staticmethod
    def _setup(user):
        """Things that are still placeholders or not connected, shown to staff on the dashboard until they are fixed."""
        todo = []

        def add(key, severity, title, detail, href):
            todo.append({'key': key, 'severity': severity, 'title': title, 'detail': detail, 'href': href})

        if user.has_perm('payments.view_businessentity'):
            entity = BusinessEntity.objects.filter(is_default=True).first()
            if entity is None or 'set legal name' in entity.legal_name.lower():
                add('legal-name', 'warning', 'Set your company legal name', 'Invoices still say "GoHyderabad (set legal name)".', '/admin/finance/business-entities')
            elif not entity.gstin:
                add('gstin', 'info', 'Add your GSTIN', 'Needed on tax invoices if you are GST-registered.', '/admin/finance/business-entities')
            gst = GstConfiguration.objects.filter(is_default=True).first()
            if gst is None or not gst.enabled:
                add('gst', 'warning', 'GST is switched off', 'Bookings are charged with no tax. Confirm the right treatment with your tax adviser, then add a GST setting.', '/admin/finance/gst-configurations')
        if user.has_perm('core.view_setting'):
            for row in Setting.objects.filter(description__contains='PLACEHOLDER'):
                add(f'setting-{row.key}', 'warning', f'Confirm "{row.key}"', 'This is still a first-run value, not a business decision. Edit it to the real value.', '/admin/system/settings')
            if not settings.RAZORPAY_KEY_ID:
                add('razorpay', 'warning', 'Online payments are not connected', 'Razorpay keys are missing, so customers cannot pay online.', '')
            if not (os.getenv('WHATSAPP_API_URL') and os.getenv('WHATSAPP_ACCESS_TOKEN')):
                add('whatsapp', 'warning', 'WhatsApp is not connected', 'Sign-in codes and booking messages cannot be sent. In development, codes only appear in the server console.', '')
            if not settings.AWS_STORAGE_BUCKET_NAME:
                add('storage', 'info', 'Files are stored on this server', 'Set the AWS bucket so uploads survive deployments.', '')
        return todo

    @staticmethod
    def _fill_days(start, end, rows):
        values = {row['day']: row['value'] or 0 for row in rows}
        result = []
        cursor = start
        while cursor <= end:
            result.append({'date': cursor.isoformat(), 'value': values.get(cursor, 0)})
            cursor += timedelta(days=1)
        return result
