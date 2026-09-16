"""External IDs are scoped to a connection and never replace local IDs."""

from django.db import models

from barbershop.catalog.models import Barber, Branch, Business, ServiceOffering


class YandexConnection(models.Model):  # type: ignore[misc]
    business = models.OneToOneField(
        Business, on_delete=models.PROTECT, related_name="yandex_connection"
    )
    partner_name = models.CharField(max_length=128, unique=True)
    catalog_read_enabled = models.BooleanField(default=False)
    availability_read_enabled = models.BooleanField(default=False)

    def __str__(self) -> str:
        return str(self.partner_name)


class YandexBranchMapping(models.Model):  # type: ignore[misc]
    connection = models.ForeignKey(
        YandexConnection, on_delete=models.PROTECT, related_name="branches"
    )
    branch = models.OneToOneField(Branch, on_delete=models.PROTECT, related_name="yandex_mapping")
    external_id = models.CharField(max_length=128, unique=True)
    permalink = models.CharField(max_length=64)
    address = models.CharField(max_length=300)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    def __str__(self) -> str:
        return str(self.external_id)


class YandexServiceMapping(models.Model):  # type: ignore[misc]
    connection = models.ForeignKey(
        YandexConnection, on_delete=models.PROTECT, related_name="services"
    )
    service = models.OneToOneField(
        ServiceOffering, on_delete=models.PROTECT, related_name="yandex_mapping"
    )
    external_id = models.CharField(max_length=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "external_id"],
                name="yandex_service_connection_external_unique",
            )
        ]

    def __str__(self) -> str:
        return str(self.external_id)


class YandexBarberMapping(models.Model):  # type: ignore[misc]
    connection = models.ForeignKey(
        YandexConnection, on_delete=models.PROTECT, related_name="barbers"
    )
    barber = models.OneToOneField(Barber, on_delete=models.PROTECT, related_name="yandex_mapping")
    external_id = models.CharField(max_length=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "external_id"],
                name="yandex_barber_connection_external_unique",
            )
        ]

    def __str__(self) -> str:
        return str(self.external_id)
