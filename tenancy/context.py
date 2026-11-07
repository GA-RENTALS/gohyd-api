from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import connection, transaction


_current_tenant = ContextVar('current_tenant', default=None)


def get_current_tenant():
    return _current_tenant.get()


def set_current_tenant(tenant):
    return _current_tenant.set(tenant)


def reset_current_tenant(token):
    _current_tenant.reset(token)


@contextmanager
def tenant_scope(tenant_id):
    from .models import Tenant

    tenant = Tenant.objects.filter(pk=tenant_id, is_active=True).first()
    if tenant is None:
        raise ValidationError('An active tenant is required for this operation.')
    with transaction.atomic():
        token = set_current_tenant(tenant)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.tenant_id', %s, true)",
                    [str(tenant.pk)],
                )
            yield tenant
        finally:
            reset_current_tenant(token)
