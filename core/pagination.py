from rest_framework.pagination import PageNumberPagination


class SitePagination(PageNumberPagination):
    """12 per page by default; callers may ask for up to 100 (?page_size=100) so the homepage needs one request, not five."""
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 100
