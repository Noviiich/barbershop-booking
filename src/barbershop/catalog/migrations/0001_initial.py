"""Create the minimal branch catalog and barber assignments."""

import uuid
from decimal import Decimal

import django.db.models.deletion
from django.core.validators import MinValueValidator, RegexValidator
from django.db import migrations, models


class Migration(migrations.Migration):  # type: ignore[misc]
    initial = True

    dependencies = [
        ("database", "0001_enable_btree_gist"),
        ("identity", "0002_owner_null_branch_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="Business",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=200)),
            ],
        ),
        migrations.CreateModel(
            name="Barber",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("display_name", models.CharField(max_length=200)),
                ("is_active", models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name="Branch",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("timezone", models.CharField(default="Europe/Moscow", max_length=64)),
                ("horizon_days", models.PositiveSmallIntegerField(default=60)),
                ("min_lead_minutes", models.PositiveIntegerField(default=30)),
                ("grid_minutes", models.PositiveSmallIntegerField(default=15)),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="branches",
                        to="catalog.business",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ServiceOffering",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                (
                    "price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[MinValueValidator(Decimal("0.00"))],
                    ),
                ),
                (
                    "currency",
                    models.CharField(
                        default="RUB",
                        max_length=3,
                        validators=[
                            RegexValidator(
                                "^[A-Z]{3}$",
                                "currency must be an ISO-like uppercase code",
                            )
                        ],
                    ),
                ),
                (
                    "duration_seconds",
                    models.PositiveIntegerField(validators=[MinValueValidator(1)]),
                ),
                ("buffer_before_seconds", models.PositiveIntegerField(default=0)),
                ("buffer_after_seconds", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="services",
                        to="catalog.branch",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="BarberAssignment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                (
                    "barber",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignments",
                        to="catalog.barber",
                    ),
                ),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignments",
                        to="catalog.branch",
                    ),
                ),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="barber_assignments",
                        to="catalog.serviceoffering",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="branch",
            constraint=models.UniqueConstraint(
                fields=("business", "name"), name="catalog_branch_business_name_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="branch",
            constraint=models.CheckConstraint(
                condition=models.Q(("horizon_days__gt", 0)), name="catalog_branch_horizon_positive"
            ),
        ),
        migrations.AddConstraint(
            model_name="branch",
            constraint=models.CheckConstraint(
                condition=models.Q(("grid_minutes__gt", 0)), name="catalog_branch_grid_positive"
            ),
        ),
        migrations.AddConstraint(
            model_name="serviceoffering",
            constraint=models.UniqueConstraint(
                fields=("branch", "name"), name="catalog_service_branch_name_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="serviceoffering",
            constraint=models.CheckConstraint(
                condition=models.Q(("price__gte", 0)), name="catalog_service_price_nonnegative"
            ),
        ),
        migrations.AddConstraint(
            model_name="serviceoffering",
            constraint=models.CheckConstraint(
                condition=models.Q(("duration_seconds__gt", 0)),
                name="catalog_service_duration_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="serviceoffering",
            constraint=models.CheckConstraint(
                condition=models.Q(("buffer_before_seconds__gte", 0))
                & models.Q(("buffer_after_seconds__gte", 0)),
                name="catalog_service_buffers_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="barberassignment",
            constraint=models.UniqueConstraint(
                fields=("branch", "barber", "service"),
                name="catalog_assignment_branch_barber_service_unique",
            ),
        ),
    ]
