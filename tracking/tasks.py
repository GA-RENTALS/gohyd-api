from celery import shared_task

from tenancy.context import tenant_scope


@shared_task(name='tracking.tasks.handle_analytics_event')
def handle_analytics_event(event_id, event_type, aggregate_id, payload, tenant_id):
    """Forward server-side conversions to PostHog (no PII, no OTPs, no payment details) - wired in Phase 6."""
    with tenant_scope(tenant_id):
        return None
