from rest_framework import pagination


class CursorPagination(pagination.CursorPagination):
    """Keyset pagination for chronological lists; IDs are time-ordered, so they break ties."""

    ordering = ("-created_at", "-id")
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
