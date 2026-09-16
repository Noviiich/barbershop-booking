import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):  # type: ignore[misc]
    initial = True
    dependencies = [
        ("catalog", "0002_remove_serviceoffering_catalog_service_buffers_nonnegative_and_more")
    ]
    operations = [
        migrations.CreateModel(
            name="YandexConnection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("partner_name", models.CharField(max_length=128, unique=True)),
                ("catalog_read_enabled", models.BooleanField(default=False)),
                ("availability_read_enabled", models.BooleanField(default=False)),
                (
                    "business",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="yandex_connection",
                        to="catalog.business",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="YandexBranchMapping",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("external_id", models.CharField(max_length=128, unique=True)),
                ("permalink", models.CharField(max_length=64)),
                ("address", models.CharField(max_length=300)),
                ("latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                (
                    "branch",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="yandex_mapping",
                        to="catalog.branch",
                    ),
                ),
                (
                    "connection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="branches",
                        to="integration.yandexconnection",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="YandexServiceMapping",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("external_id", models.CharField(max_length=128)),
                (
                    "connection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="services",
                        to="integration.yandexconnection",
                    ),
                ),
                (
                    "service",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="yandex_mapping",
                        to="catalog.serviceoffering",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("connection", "external_id"),
                        name="yandex_service_connection_external_unique",
                    )
                ]
            },
        ),
        migrations.CreateModel(
            name="YandexBarberMapping",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("external_id", models.CharField(max_length=128)),
                (
                    "barber",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="yandex_mapping",
                        to="catalog.barber",
                    ),
                ),
                (
                    "connection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="barbers",
                        to="integration.yandexconnection",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("connection", "external_id"),
                        name="yandex_barber_connection_external_unique",
                    )
                ]
            },
        ),
    ]
