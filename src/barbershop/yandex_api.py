"""Disabled-by-default HTTP boundary for Yandex catalog and slots reads."""

from datetime import date
from typing import cast

from django.conf import settings
from django.http import Http404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from barbershop.integration.auth import YandexAuthenticationError, authenticate
from barbershop.integration.models import YandexConnection
from barbershop.integration.reads import (
    YandexReadError,
    branch_for,
    feed,
    resources,
    services,
    slots,
)


class YandexReadView(APIView):  # type: ignore[misc]
    authentication_classes: list[object] = []
    permission_classes: list[object] = []

    def _connection(
        self, request: Request, claims: dict[str, str] | None = None
    ) -> YandexConnection:
        if not settings.YANDEX_BOOKING_READ_ENABLED:
            raise Http404
        try:
            authenticate(request.headers.get("Authorization", ""), expected_claims=claims)
            return cast(
                YandexConnection,
                YandexConnection.objects.get(partner_name=settings.YANDEX_BOOKING_PARTNER_NAME),
            )
        except (YandexAuthenticationError, YandexConnection.DoesNotExist) as error:
            raise Http404 from error


class YandexFeedView(YandexReadView):
    def get(self, request: Request) -> Response:
        connection = self._connection(request)
        if not connection.catalog_read_enabled:
            raise Http404
        try:
            count = int(request.query_params.get("count", "100"))
            if not 1 <= count <= 500:
                raise ValueError
        except ValueError:
            return Response({"code": "INVALID_REQUEST"}, status=422)
        return Response(feed(connection, request.query_params.get("cursor"), count))


class YandexCompanyView(YandexReadView):
    mode = ""

    def get(self, request: Request, company_id: str) -> Response:
        connection = self._connection(request, {"companyId": company_id})
        if not connection.catalog_read_enabled:
            raise Http404
        try:
            mapping = branch_for(connection, company_id)
        except YandexReadError as error:
            raise Http404 from error
        return Response(services(mapping) if self.mode == "services" else resources(mapping))


class YandexSlotsView(YandexReadView):
    def get(self, request: Request, company_id: str) -> Response:
        connection = self._connection(request, {"companyId": company_id})
        if not connection.availability_read_enabled:
            raise Http404
        service_ids = request.query_params.getlist("serviceIds[]")
        try:
            mapping = branch_for(connection, company_id)
            local_date = date.fromisoformat(request.query_params["date"])
            if not service_ids:
                raise ValueError
            return Response(
                slots(mapping, service_ids, request.query_params.get("resourceId"), local_date)
            )
        except (KeyError, ValueError, YandexReadError):
            return Response({"code": "INVALID_REQUEST"}, status=422)
