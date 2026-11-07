from django.conf import settings
from django.http import HttpResponse


class RequestSizeLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.max_request_bytes = settings.MAX_REQUEST_BODY_BYTES

    def __call__(self, request):
        content_length = request.META.get('CONTENT_LENGTH')
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                return HttpResponse(status=400)
            if body_size < 0:
                return HttpResponse(status=400)
            if body_size > self.max_request_bytes:
                return HttpResponse(status=413)
        return self.get_response(request)
