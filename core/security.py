import ipaddress

from django.conf import settings


def get_client_ip(request):
    remote_addr = request.META.get('REMOTE_ADDR', '')
    try:
        remote = ipaddress.ip_address(remote_addr)
    except ValueError:
        return None

    trusted_proxies = settings.TRUSTED_PROXY_NETWORKS

    if not any(remote in network for network in trusted_proxies):
        return str(remote)

    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if not forwarded:
        return str(remote)

    try:
        chain = [ipaddress.ip_address(value.strip()) for value in forwarded.split(',')]
    except ValueError:
        return str(remote)

    chain.append(remote)
    index = len(chain) - 1
    while index > 0 and any(chain[index] in network for network in trusted_proxies):
        index -= 1
    return str(chain[index])
