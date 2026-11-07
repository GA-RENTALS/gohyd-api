from core.admin import register_remaining

register_remaining('notifications', readonly=('NotificationDeliveryLog', 'NotificationFailure', 'WebhookRecord', 'WebhookLog', 'IntegrationExecutionLog', 'SystemHealthLog'))
