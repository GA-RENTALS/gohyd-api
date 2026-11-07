import hashlib

from django.core.exceptions import FieldDoesNotExist
from django.db import migrations


TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"


def _tenant_relation_conditions(through, quote_name):
    conditions = []
    for field in through._meta.fields:
        if not field.many_to_one or field.remote_field is None:
            continue
        related_model = field.remote_field.model
        try:
            tenant_field = related_model._meta.get_field('tenant')
        except FieldDoesNotExist:
            if related_model._meta.label_lower != 'accounts.user':
                continue
            alias = f'related_{len(conditions)}'
            through_table = quote_name(through._meta.db_table)
            membership_table = quote_name('tenant_memberships')
            conditions.append(
                f'EXISTS (SELECT 1 FROM {membership_table} AS {alias} '
                f'WHERE {alias}.{quote_name("user_id")} = {through_table}.{quote_name(field.column)} '
                f'AND {alias}.{quote_name("tenant_id")}::text = {TENANT_GUC} '
                f'AND {alias}.{quote_name("is_active")})'
            )
            continue
        alias = f'related_{len(conditions)}'
        related_table = quote_name(related_model._meta.db_table)
        through_table = quote_name(through._meta.db_table)
        conditions.append(
            f'EXISTS (SELECT 1 FROM {related_table} AS {alias} '
            f'WHERE {alias}.{quote_name(related_model._meta.pk.column)} = '
            f'{through_table}.{quote_name(field.column)} '
            f'AND {alias}.{quote_name(tenant_field.column)}::text = {TENANT_GUC})'
        )
    return conditions


def _apply_policy(cursor, quote_name, table, using, check):
    policy = quote_name(f'tenant_scope_{hashlib.sha256(table.encode()).hexdigest()[:10]}')
    quoted_table = quote_name(table)
    cursor.execute(f'ALTER TABLE {quoted_table} ENABLE ROW LEVEL SECURITY')
    cursor.execute(f'ALTER TABLE {quoted_table} FORCE ROW LEVEL SECURITY')
    cursor.execute(
        f'CREATE POLICY {policy} ON {quoted_table} USING ({using}) WITH CHECK ({check})'
    )


def enable_tenant_rls(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        raise RuntimeError('Tenant RLS requires PostgreSQL.')

    quote_name = schema_editor.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND column_name = 'tenant_id' "
            "AND table_name <> 'tenant_domains' "
            "AND table_name IN (SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE')"
        )
        tenant_tables = [row[0] for row in cursor.fetchall()]
        for table in tenant_tables:
            tenant_check = f'{quote_name("tenant_id")}::text = {TENANT_GUC}'
            _apply_policy(cursor, quote_name, table, tenant_check, tenant_check)

        through_tables = {}
        for model in apps.get_models():
            for field in model._meta.local_many_to_many:
                through = field.remote_field.through
                if not through._meta.auto_created:
                    continue
                conditions = _tenant_relation_conditions(through, quote_name)
                if conditions:
                    through_tables[through._meta.db_table] = ' AND '.join(conditions)

        for table, condition in through_tables.items():
            _apply_policy(cursor, quote_name, table, condition, condition)


def disable_tenant_rls(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        return
    quote_name = schema_editor.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        )
        for (table,) in cursor.fetchall():
            cursor.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name = %s AND column_name = 'tenant_id'",
                [table],
            )
            has_tenant = cursor.fetchone() is not None
            if has_tenant and table != 'tenant_domains':
                policy = quote_name(f'tenant_scope_{hashlib.sha256(table.encode()).hexdigest()[:10]}')
                quoted_table = quote_name(table)
                cursor.execute(f'DROP POLICY IF EXISTS {policy} ON {quoted_table}')
                cursor.execute(f'ALTER TABLE {quoted_table} NO FORCE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE {quoted_table} DISABLE ROW LEVEL SECURITY')

        for model in apps.get_models():
            for field in model._meta.local_many_to_many:
                through = field.remote_field.through
                if not through._meta.auto_created:
                    continue
                if not _tenant_relation_conditions(through, quote_name):
                    continue
                table = through._meta.db_table
                policy = quote_name(f'tenant_scope_{hashlib.sha256(table.encode()).hexdigest()[:10]}')
                quoted_table = quote_name(table)
                cursor.execute(f'DROP POLICY IF EXISTS {policy} ON {quoted_table}')
                cursor.execute(f'ALTER TABLE {quoted_table} NO FORCE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE {quoted_table} DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0002_gohyderabad_tenant_backfill'),
    ]

    operations = [
        migrations.RunPython(enable_tenant_rls, disable_tenant_rls),
    ]
