"""Team & roles: who works in the admin, what each role may do, and inviting / changing / deactivating staff.

GET   /admin/team/            staff list, the roles with a plain-language access matrix, and what you may change
POST  /admin/team/            invite: {name, phone, role}
PATCH /admin/team/<user_id>/  {role} and/or {active}

A role is one of the permission groups created by `seed_platform`. Each staff member has exactly one. Access to the
operator comes from their TenantMembership (STAFF or TENANT_ADMIN), so deactivating someone switches off that membership
and every admin request fails from the next call; their user account (and any customer bookings) is kept.

Only tenant admins and platform superusers can change the team, nobody can change their own access, only superusers can
hand out "Super Admin", and the last active admin can't be removed.
"""
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.http import Http404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import LoginHistory, User, normalize_phone
from core.management.commands.seed_platform import ROLES
from tenancy.models import TenantMembership

from .overview import _iso
from .permissions import StaffOnly, staff_has_perm
from .views import _audit, _resolve

STAFF_ROLES = (TenantMembership.Role.STAFF, TenantMembership.Role.TENANT_ADMIN)
ADMIN_ROLES = {'Super Admin', 'Admin'}          # these roles make the person a tenant admin
SUPERUSER_ONLY_ROLES = {'Super Admin'}

ROLE_DESCRIPTIONS = {
    'Super Admin': 'Everything, including platform settings. Only platform administrators can give this role.',
    'Admin': 'Everything for this business, including the team.',
    'Content Manager': 'Writes and publishes website content; can see trips.',
    'Content Writer': 'Writes website content for someone else to publish.',
    'Trip Manager': 'Creates and runs trips, dates and operations; can see bookings.',
    'Trip Organizer': 'Runs trips on the day: participants, check-in and operations.',
    'Booking Manager': 'Manages bookings, cancellations and departure exceptions; can see payments.',
    'Finance Manager': 'Payments, refunds, invoices and expenses.',
    'Customer Support': 'Enquiries, support tickets and customer bookings.',
    'Marketing Manager': 'Coupons, campaigns, CRM and customer messages.',
    'Operations Manager': 'Vendors, vehicles, drivers, safety and incidents.',
    'Analytics Viewer': 'Read-only reports, bookings and payments.',
}

# Areas shown in the role matrix -> the Django apps behind them.
AREAS = [
    ('trips', 'Trips & events', ('trips',)),
    ('bookings', 'Bookings', ('bookings',)),
    ('payments', 'Payments & finance', ('payments',)),
    ('customers', 'Customers & CRM', ('accounts', 'crm')),
    ('website', 'Website content', ('content',)),
    ('operations', 'Operations', ('operations',)),
    ('reports', 'Reports', ('tracking',)),
    ('messages', 'Messages', ('notifications',)),
]


# ---------- who may do what ----------

def _membership(request, user=None):
    return TenantMembership.objects.filter(tenant=request.tenant, user=user or request.user).first()


def can_manage_team(request):
    if request.user.is_superuser:
        return True
    membership = _membership(request)
    return bool(membership and membership.is_active and membership.role == TenantMembership.Role.TENANT_ADMIN)


def can_view_team(request):
    return can_manage_team(request) or staff_has_perm(request, 'tenancy.view_tenantmembership')


def _require_manage(request):
    if not can_manage_team(request):
        raise PermissionDenied('Only admins can change the team.')


def assignable_roles(request):
    return [name for name in ROLES if request.user.is_superuser or name not in SUPERUSER_ONLY_ROLES]


# ---------- roles and the access matrix ----------

def _level(codenames):
    actions = {code.split('_', 1)[0] for code in codenames}
    if 'delete' in actions:
        return 'full'
    if actions & {'add', 'change'}:
        return 'edit'
    return 'view' if 'view' in actions else ''


def role_matrix():
    """[{name, description, access: {area: '' | 'view' | 'edit' | 'full'}}] from the groups' real permissions."""
    groups = {g.name: g for g in Group.objects.filter(name__in=ROLES).prefetch_related('permissions__content_type')}
    out = []
    for name in ROLES:
        group = groups.get(name)
        perms = [(p.content_type.app_label, p.codename) for p in group.permissions.all()] if group else []
        access = {key: _level([code for app, code in perms if app in apps]) for key, _, apps in AREAS}
        out.append({'name': name, 'description': ROLE_DESCRIPTIONS.get(name, ''), 'access': access, 'exists': group is not None})
    return out


def _role_of(user):
    return next((g.name for g in user.groups.all() if g.name in ROLES), '')


def _set_role(user, role):
    group = Group.objects.filter(name=role).first()
    if group is None:
        raise ValidationError({'role': f'The role "{role}" has not been set up yet. Run seed_platform first.'})
    user.groups.remove(*user.groups.filter(name__in=ROLES))
    user.groups.add(group)


# ---------- rows ----------

def _staff(request):
    return (TenantMembership.objects.filter(tenant=request.tenant, role__in=STAFF_ROLES)
            .select_related('user').prefetch_related('user__groups').order_by('-is_active', 'user__full_name', 'user__phone_number'))


def staff_rows(request, memberships):
    last = dict(LoginHistory.objects.filter(user_id__in=[m.user_id for m in memberships], success=True)
                .values('user_id').annotate(at=Max('created_at')).values_list('user_id', 'at'))
    return [{
        'id': str(m.user_id), 'name': m.user.full_name or m.user.phone_number, 'phone': m.user.phone_number, 'email': m.user.email,
        'role': _role_of(m.user), 'is_admin': m.role == TenantMembership.Role.TENANT_ADMIN, 'active': m.is_active,
        'last_sign_in': _iso(last.get(m.user_id)), 'added_at': _iso(m.created_at), 'is_you': m.user_id == request.user.pk,
        'is_superuser': m.user.is_superuser,
    } for m in memberships]


class RoleField(serializers.CharField):
    """A role name this staff member is allowed to hand out."""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value not in assignable_roles(self.context['request']):
            raise serializers.ValidationError('Choose one of the listed roles.')
        return value


class InviteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    role = RoleField(max_length=80)

    def validate_phone(self, value):
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0])


class UpdateSerializer(serializers.Serializer):
    role = RoleField(max_length=80, required=False)
    active = serializers.BooleanField(required=False)


# ---------- views ----------

class TeamView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request):
        if not can_view_team(request):
            raise PermissionDenied('You do not have access to the team list.')
        search = request.query_params.get('search', '').strip()
        qs = _staff(request)
        if search:
            qs = qs.filter(Q(user__full_name__icontains=search) | Q(user__phone_number__icontains=search) | Q(user__email__icontains=search))
        manage = can_manage_team(request)
        return Response({
            'results': staff_rows(request, list(qs)),
            'roles': role_matrix(),
            'areas': [{'key': key, 'label': label} for key, label, _ in AREAS],
            'can': {'manage': manage, 'roles': assignable_roles(request) if manage else []},
        })

    def post(self, request):
        _require_manage(request)
        data = InviteSerializer(data=request.data, context={'request': request})
        data.is_valid(raise_exception=True)
        name, phone, role = data.validated_data['name'].strip(), data.validated_data['phone'], data.validated_data['role']

        with transaction.atomic():
            user = User.objects.filter(phone_number=phone).first()
            if user is None:
                # They sign in with a WhatsApp code, so no password is set or shared.
                user = User.objects.create_user(phone, full_name=name, is_staff=True, kind=User.Kind.ADMIN)
            else:
                if user.is_superuser and not request.user.is_superuser:
                    raise PermissionDenied('This person is a platform administrator.')
                if not user.full_name:
                    user.full_name = name
                user.is_staff = True
                user.save(update_fields=['is_staff', 'full_name'])
            membership, _ = TenantMembership.objects.get_or_create(tenant=request.tenant, user=user)
            if membership.role in STAFF_ROLES and membership.is_active:
                raise ValidationError({'phone': 'This person is already on the team.'})
            membership.role = TenantMembership.Role.TENANT_ADMIN if role in ADMIN_ROLES else TenantMembership.Role.STAFF
            membership.is_active = True
            membership.save(update_fields=['role', 'is_active'])
            _set_role(user, role)
            _audit(request, 'team.invite', _resolve('staff-memberships'), membership, after={'user': str(user.pk), 'role': role})
        return Response(staff_rows(request, [membership])[0], status=status.HTTP_201_CREATED)


class TeamMemberView(APIView):
    permission_classes = [StaffOnly]

    def patch(self, request, pk):
        _require_manage(request)
        membership = _staff(request).filter(user_id=pk).first() if str(pk).isdigit() else None
        if membership is None:
            raise Http404('Team member not found.')
        if membership.user_id == request.user.pk:
            raise PermissionDenied('You cannot change your own access. Ask another admin.')
        if membership.user.is_superuser and not request.user.is_superuser:
            raise PermissionDenied('Platform administrators can only be changed by another platform administrator.')
        data = UpdateSerializer(data=request.data, context={'request': request})
        data.is_valid(raise_exception=True)
        role, active = data.validated_data.get('role'), data.validated_data.get('active')
        if role is None and active is None:
            raise ValidationError({'detail': 'Send a role or active.'})

        before = {'role': _role_of(membership.user), 'active': membership.is_active, 'admin': membership.role}
        with transaction.atomic():
            will_be_admin = (role in ADMIN_ROLES) if role is not None else membership.role == TenantMembership.Role.TENANT_ADMIN
            will_be_active = membership.is_active if active is None else active
            if membership.role == TenantMembership.Role.TENANT_ADMIN and not (will_be_admin and will_be_active):
                self._keep_one_admin(request, membership)
            if role is not None:
                _set_role(membership.user, role)
                membership.role = TenantMembership.Role.TENANT_ADMIN if will_be_admin else TenantMembership.Role.STAFF
            membership.is_active = will_be_active
            membership.save(update_fields=['role', 'is_active'])
            _audit(request, 'team.update', _resolve('staff-memberships'), membership, before=before,
                   after={'role': _role_of(membership.user), 'active': membership.is_active, 'admin': membership.role})
        membership.user.refresh_from_db()
        return Response(staff_rows(request, [membership])[0])

    @staticmethod
    def _keep_one_admin(request, membership):
        others = (TenantMembership.objects.select_for_update()
                  .filter(tenant=request.tenant, role=TenantMembership.Role.TENANT_ADMIN, is_active=True).exclude(pk=membership.pk))
        if not others.exists():
            raise ValidationError({'detail': 'This is the last active admin. Make someone else an admin first.'})
