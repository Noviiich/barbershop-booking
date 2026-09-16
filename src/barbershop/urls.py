"""Root URL configuration for the empty backend scaffold."""

from django.urls import path
from drf_spectacular.views import SpectacularAPIView

from barbershop.api import (
    AvailabilityView,
    BookingCollectionView,
    BookingDetailView,
    CancelBookingView,
    CompleteBookingView,
    MarkNoShowView,
    RescheduleBookingView,
)
from barbershop.health import health
from barbershop.yandex_api import YandexCompanyView, YandexFeedView, YandexSlotsView

urlpatterns = [
    path("health/", health, name="health"),
    path("companies/feed", YandexFeedView.as_view(), name="yandex-feed"),
    path(
        "companies/<str:company_id>/services",
        YandexCompanyView.as_view(mode="services"),
        name="yandex-services",
    ),
    path(
        "companies/<str:company_id>/resources",
        YandexCompanyView.as_view(mode="resources"),
        name="yandex-resources",
    ),
    path(
        "companies/<str:company_id>/available_time_slots",
        YandexSlotsView.as_view(),
        name="yandex-slots",
    ),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/v1/bookings/", BookingCollectionView.as_view(), name="booking-create"),
    path("api/v1/availability/", AvailabilityView.as_view(), name="booking-availability"),
    path("api/v1/bookings/<uuid:booking_id>/", BookingDetailView.as_view(), name="booking-detail"),
    path(
        "api/v1/bookings/<uuid:booking_id>/cancel/",
        CancelBookingView.as_view(),
        name="booking-cancel",
    ),
    path(
        "api/v1/bookings/<uuid:booking_id>/reschedule/",
        RescheduleBookingView.as_view(),
        name="booking-reschedule",
    ),
    path(
        "api/v1/bookings/<uuid:booking_id>/complete/",
        CompleteBookingView.as_view(),
        name="booking-complete",
    ),
    path(
        "api/v1/bookings/<uuid:booking_id>/no-show/",
        MarkNoShowView.as_view(),
        name="booking-no-show",
    ),
]
