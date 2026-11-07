from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle

from .security import get_client_ip


class TrustedClientIdentityMixin:
    def get_ident(self, request):
        return get_client_ip(request._request) or 'unknown'


class TrustedAnonRateThrottle(TrustedClientIdentityMixin, AnonRateThrottle):
    pass


class TrustedScopedRateThrottle(TrustedClientIdentityMixin, ScopedRateThrottle):
    pass


class TrustedUserRateThrottle(TrustedClientIdentityMixin, UserRateThrottle):
    pass
