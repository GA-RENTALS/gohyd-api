from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db import connections


@register(Tags.database)
def tenant_rls_database_check(app_configs, **kwargs):
    if not getattr(settings, 'TENANT_RLS_ENABLED', True):
        return [Error('Tenant RLS is disabled.', id='tenancy.E001')]
    if settings.DEBUG:
        return []

    errors = []
    for alias in connections:
        connection = connections[alias]
        if connection.vendor != 'postgresql':
            errors.append(Error(
                f'Database {alias!r} must use PostgreSQL for tenant row-level security.',
                id='tenancy.E002',
            ))
            continue
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user'
                )
                row = cursor.fetchone()
        except Exception as exc:
            errors.append(Error(
                f'Could not verify the RLS capabilities of database {alias!r}: {exc.__class__.__name__}.',
                id='tenancy.E003',
            ))
            continue
        if not row or row[0]:
            errors.append(Error(
                f'Database role for {alias!r} must be NOSUPERUSER and NOBYPASSRLS.',
                id='tenancy.E004',
            ))
    return errors
