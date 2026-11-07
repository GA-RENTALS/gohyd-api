from core.admin import register_remaining

register_remaining('tracking', readonly=('VisitorEvent', 'VisitorSession', 'TrackingConsent', 'ConversionEvent'))
