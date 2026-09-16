"""Thin DRF transport over the transactional booking application services."""

from typing import cast
from uuid import UUID, uuid4

from django.http import Http404
from drf_spectacular.utils import OpenApiTypes, extend_schema  # type: ignore[attr-defined]
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from barbershop.booking.availability import (
    AvailabilityQuery,
    AvailabilityQueryError,
    list_available_slots,
)
from barbershop.booking.cancellation import CancelBookingCommand, cancel_booking
from barbershop.booking.models import Booking
from barbershop.booking.outcomes import BookingOutcomeCommand, complete_booking, mark_no_show
from barbershop.booking.rescheduling import RescheduleBookingCommand, reschedule_booking
from barbershop.booking.services import CreateBookingCommand, create_booking
from barbershop.idempotency.models import CommandReceipt
from barbershop.idempotency.services import CommandScope, IdempotencyConflict
from barbershop.identity.models import StaffScope
from barbershop.identity.policy import AccessDenied, Principal
from barbershop.identity.rate_limit import RateLimitExceeded, enforce_mutation_limit
from barbershop.identity.tokens import (
    ManagementTokenError,
    authorize_management_token,
    decrypt_management_token,
    issue_management_token,
)


class CreateBookingSerializer(serializers.Serializer[dict[str, object]]):  # type: ignore[misc]
    branch_id = serializers.UUIDField()
    barber_id = serializers.UUIDField()
    service_id = serializers.IntegerField(min_value=1)
    start_at = serializers.DateTimeField()


class RescheduleSerializer(serializers.Serializer[dict[str, object]]):  # type: ignore[misc]
    expected_version = serializers.IntegerField(min_value=1)
    start_at = serializers.DateTimeField()


class VersionSerializer(serializers.Serializer[dict[str, object]]):  # type: ignore[misc]
    expected_version = serializers.IntegerField(min_value=1)


class AvailabilitySerializer(serializers.Serializer[dict[str, object]]):  # type: ignore[misc]
    business_id = serializers.UUIDField()
    branch_id = serializers.UUIDField()
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    barber_id = serializers.UUIDField(required=False)
    service_id = serializers.IntegerField(min_value=1, required=False)
    limit = serializers.IntegerField(min_value=1, max_value=500, default=100)


def _no_store(response: Response) -> Response:
    response["Cache-Control"] = "no-store"
    return response


def _session_key(request: Request) -> str:
    if request.session.session_key is None:
        request.session.create()
    assert request.session.session_key is not None
    return cast(str, request.session.session_key)


def _idempotency_key(request: Request) -> str:
    key = request.headers.get("Idempotency-Key", "")
    if not key or len(key) > 128:
        raise serializers.ValidationError({"Idempotency-Key": "required; maximum length is 128"})
    return cast(str, key)


def _token_from_request(request: Request) -> str | None:
    prefix = "Booking "
    value = request.headers.get("Authorization", "")
    return cast(str, value[len(prefix) :]) if value.startswith(prefix) else None


def _guest_scope(
    request: Request, business_id: UUID, target_id: UUID | None = None
) -> CommandScope:
    return CommandScope(
        business_id=business_id,
        principal_kind="GUEST",
        principal_id=_session_key(request),
        channel="OWN_API",
        target_id=target_id,
    )


def _booking_data(booking: Booking) -> dict[str, object]:
    return {
        "id": str(booking.id),
        "branch_id": str(booking.branch_id),
        "barber_id": str(booking.barber_id),
        "service_id": booking.service_id,
        "status": booking.status,
        "version": booking.version,
        "start_at": booking.start_at,
        "end_at": booking.end_at,
    }


def _booking_or_404(booking_id: UUID) -> Booking:
    try:
        return cast(Booking, Booking.objects.select_related("branch").get(pk=booking_id))
    except Booking.DoesNotExist as error:
        raise Http404 from error


def _guest_booking(request: Request, booking_id: UUID) -> Booking:
    booking = _booking_or_404(booking_id)
    authorize_management_token(
        booking_id=booking.id,
        raw_token=_token_from_request(request),
        session_key=_session_key(request),
    )
    return booking


class BookingCollectionView(APIView):  # type: ignore[misc]
    """Create a guest booking and issue its one-booking management capability."""

    authentication_classes: list[object] = []
    permission_classes: list[object] = []

    @extend_schema(request=CreateBookingSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        serializer = CreateBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch_id = data["branch_id"]
        assert isinstance(branch_id, UUID)
        from barbershop.catalog.models import Branch

        try:
            branch = Branch.objects.get(pk=branch_id)
        except Branch.DoesNotExist as error:
            raise Http404 from error
        key = _idempotency_key(request)
        session_key = _session_key(request)
        scope = _guest_scope(request, branch.business_id)
        try:
            enforce_mutation_limit(scope.digest())
        except RateLimitExceeded:
            return _no_store(Response({"code": "RATE_LIMITED"}, status=429))
        issued = issue_management_token()
        command = CreateBookingCommand(
            scope=scope,
            idempotency_key=key,
            branch_id=branch_id,
            barber_id=data["barber_id"],
            service_id=data["service_id"],
            start_at=data["start_at"],
            correlation_id=uuid4(),
            management_token_hash=issued.token_hash,
            management_token_encrypted=issued.encrypted,
            guest_session_key=session_key,
        )
        try:
            result = create_booking(command)
        except IdempotencyConflict:
            return _no_store(Response({"code": "IDEMPOTENCY_KEY_MISMATCH"}, status=409))
        body: dict[str, object] = {
            "code": result.result_code,
            "booking_id": str(result.booking_id) if result.booking_id else None,
            "version": result.version,
        }
        if result.result_code == "CREATED":
            token = issued.raw
            if result.replayed:
                receipt = CommandReceipt.objects.get(
                    scope_digest=scope.digest(), operation="CREATE_BOOKING", idempotency_key=key
                )
                encrypted = receipt.response.get("management_token_encrypted", "")
                if isinstance(encrypted, str):
                    token = decrypt_management_token(encrypted)
            body["management_token"] = token
            return _no_store(Response(body, status=201))
        return _no_store(
            Response(body, status=409 if result.result_code == "SLOT_CONFLICT" else 422)
        )


class BookingDetailView(APIView):  # type: ignore[misc]
    authentication_classes: list[object] = []
    permission_classes: list[object] = []

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, booking_id: UUID) -> Response:
        try:
            booking = _guest_booking(request, booking_id)
        except ManagementTokenError:
            return _no_store(Response({"code": "NOT_FOUND"}, status=404))
        return _no_store(Response(_booking_data(booking)))


class AvailabilityView(APIView):  # type: ignore[misc]
    """Expose bounded primary-DB slot candidates without creating a reservation."""

    authentication_classes: list[object] = []
    permission_classes: list[object] = []

    @extend_schema(parameters=[AvailabilitySerializer], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        serializer = AvailabilitySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            slots = list_available_slots(AvailabilityQuery(**data))
        except AvailabilityQueryError:
            return _no_store(Response({"code": "NOT_FOUND"}, status=404))
        return _no_store(
            Response(
                {
                    "slots": [
                        {
                            "start_at": slot.start_at,
                            "end_at": slot.end_at,
                            "barber_id": str(slot.barber_id),
                            "service_id": slot.service_id,
                        }
                        for slot in slots
                    ]
                }
            )
        )


class GuestCommandView(APIView):  # type: ignore[misc]
    authentication_classes: list[object] = []
    permission_classes: list[object] = []
    action = ""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, booking_id: UUID) -> Response:
        try:
            booking = _guest_booking(request, booking_id)
        except ManagementTokenError:
            return _no_store(Response({"code": "NOT_FOUND"}, status=404))
        key = _idempotency_key(request)
        scope = _guest_scope(request, booking.branch.business_id, booking.id)
        try:
            enforce_mutation_limit(scope.digest())
        except RateLimitExceeded:
            return _no_store(Response({"code": "RATE_LIMITED"}, status=429))
        if self.action == "cancel":
            serializer = VersionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            result_code: str
            result_version: int
            result_no_op: bool
            cancel_result = cancel_booking(
                CancelBookingCommand(
                    scope, key, booking.id, serializer.validated_data["expected_version"], uuid4()
                )
            )
            result_code, result_version, result_no_op = (
                cancel_result.result_code,
                cancel_result.version,
                cancel_result.no_op,
            )
        else:
            serializer = RescheduleSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            reschedule_result = reschedule_booking(
                RescheduleBookingCommand(
                    scope,
                    key,
                    booking.id,
                    serializer.validated_data["expected_version"],
                    serializer.validated_data["start_at"],
                    uuid4(),
                )
            )
            result_code, result_version, result_no_op = (
                reschedule_result.result_code,
                reschedule_result.version,
                reschedule_result.no_op,
            )
        status = 200 if result_code in {"CANCELLED", "RESCHEDULED"} else 409
        return _no_store(
            Response(
                {
                    "code": result_code,
                    "booking_id": str(booking.id),
                    "version": result_version,
                    "no_op": result_no_op,
                },
                status=status,
            )
        )


class CancelBookingView(GuestCommandView):
    action = "cancel"

    @extend_schema(request=VersionSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, booking_id: UUID) -> Response:
        return super().post(request, booking_id)


class RescheduleBookingView(GuestCommandView):
    action = "reschedule"

    @extend_schema(request=RescheduleSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, booking_id: UUID) -> Response:
        return super().post(request, booking_id)


class StaffOutcomeView(APIView):  # type: ignore[misc]
    """Session-authenticated staff transport for terminal booking outcomes."""

    action = ""

    @extend_schema(request=VersionSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, booking_id: UUID) -> Response:
        if not request.user.is_authenticated:
            return _no_store(Response({"code": "AUTHENTICATION_REQUIRED"}, status=401))
        booking = _booking_or_404(booking_id)
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_id = request.user.pk
        assert isinstance(user_id, int)
        scopes = StaffScope.objects.filter(user_id=user_id)
        principal = Principal(
            user_id=user_id,
            roles=frozenset(scopes.values_list("role", flat=True)),
            branch_ids=frozenset(
                scopes.exclude(branch_id__isnull=True).values_list("branch_id", flat=True)
            ),
        )
        command = BookingOutcomeCommand(
            scope=CommandScope(
                business_id=booking.branch.business_id,
                principal_kind="USER",
                principal_id=str(user_id),
                channel="OWN_API",
                target_id=booking.id,
            ),
            principal=principal,
            idempotency_key=_idempotency_key(request),
            booking_id=booking.id,
            expected_version=serializer.validated_data["expected_version"],
            correlation_id=uuid4(),
        )
        try:
            enforce_mutation_limit(command.scope.digest())
        except RateLimitExceeded:
            return _no_store(Response({"code": "RATE_LIMITED"}, status=429))
        try:
            result = (
                complete_booking(command) if self.action == "complete" else mark_no_show(command)
            )
        except AccessDenied:
            return _no_store(Response({"code": "FORBIDDEN"}, status=403))
        status = 200 if result.result_code in {"COMPLETED", "NO_SHOW"} else 409
        return _no_store(
            Response(
                {
                    "code": result.result_code,
                    "booking_id": str(result.booking_id),
                    "version": result.version,
                    "no_op": result.no_op,
                },
                status=status,
            )
        )


class CompleteBookingView(StaffOutcomeView):
    action = "complete"


class MarkNoShowView(StaffOutcomeView):
    action = "no-show"
