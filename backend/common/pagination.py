from typing import Any

from rest_framework import pagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param
from rest_framework.views import APIView


class CursorPagination(pagination.CursorPagination):
    """Keyset pagination for chronological lists; IDs are time-ordered, so they break ties."""

    ordering = ("-created_at", "-id")
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class RankedPagination(pagination.BasePagination):
    """Offset pagination for lists ordered by a computed rank, where a cursor cannot work.

    Deliberately limited: no total count (it would cost a second full query), and no paging
    past ``max_results``, since deep offsets get slower the further they go. The response has
    the same shape as cursor pagination, so clients just follow ``next``.
    """

    page_size = 20
    max_page_size = 50
    max_results = 500
    page_size_query_param = "page_size"
    offset_query_param = "offset"

    def paginate_queryset(
        self, queryset: Any, request: Request, view: APIView | None = None
    ) -> list[Any]:
        self.request = request
        size = self._query_int(self.page_size_query_param, self.page_size)
        self.limit = min(size, self.max_page_size) if size > 0 else self.page_size
        self.offset = min(max(self._query_int(self.offset_query_param, 0), 0), self.max_results)
        # One extra row tells us whether there is a next page, without counting.
        window = min(self.limit, self.max_results - self.offset)
        rows = list(queryset[self.offset : self.offset + window + 1]) if window > 0 else []
        self.has_next = len(rows) > window and self.offset + window < self.max_results
        return rows[:window]

    def _query_int(self, param: str, default: int) -> int:
        try:
            return int(self.request.query_params.get(param, default))
        except ValueError:
            return default

    def _link(self, offset: int) -> str:
        url = self.request.build_absolute_uri()
        if offset <= 0:
            return remove_query_param(url, self.offset_query_param)
        return replace_query_param(url, self.offset_query_param, offset)

    def get_paginated_response(self, data: Any) -> Response:
        return Response(
            {
                "next": self._link(self.offset + self.limit) if self.has_next else None,
                "previous": self._link(self.offset - self.limit) if self.offset > 0 else None,
                "results": data,
            }
        )

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        link = {"type": "string", "format": "uri", "nullable": True}
        return {
            "type": "object",
            "required": ["results"],
            "properties": {"next": link, "previous": link, "results": schema},
        }
