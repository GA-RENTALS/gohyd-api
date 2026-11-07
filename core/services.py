from django.conf import settings
from django.db import transaction

from .security import get_client_ip
from .models import AuditLog, OutboxEvent, Setting

_DEFAULTS = {
    'advance.default_basis_points': lambda: settings.DEFAULT_ADVANCE_BASIS_POINTS,
    'balance.default_due_days_before': lambda: settings.DEFAULT_BALANCE_DUE_DAYS_BEFORE,
}


def get_setting(key, default=None):
    """Admin-editable value, falling back to the env/settings default."""
    row = Setting.objects.filter(key=key).first()
    if row is not None:
        return row.value
    if key in _DEFAULTS:
        return _DEFAULTS[key]()
    return default


def audit(actor, action, entity, entity_id='', before=None, after=None, request=None):
    """Write an audit row. Call inside the same transaction as the change it describes."""
    ip = ua = None
    if request is not None:
        ip = get_client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', '')[:300]
    return AuditLog.objects.create(
        actor=actor if getattr(actor, 'pk', None) else None, action=action,
        entity_type=entity if isinstance(entity, str) else entity.__class__.__name__,
        entity_id=str(entity_id or getattr(entity, 'pk', '') or ''), before=before, after=after, ip=ip, user_agent=ua or '',
    )


def emit(event_type, aggregate_id, payload=None):
    """Queue an outbox event; joins the caller's transaction if there is one."""
    return OutboxEvent.objects.create(type=event_type, aggregate_id=str(aggregate_id), payload=payload or {})
