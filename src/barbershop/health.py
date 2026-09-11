"""Process health endpoint without business or database dependencies."""

from django.http import HttpRequest, JsonResponse


def health(request: HttpRequest) -> JsonResponse:
    del request
    return JsonResponse({"status": "ok"})
