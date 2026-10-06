import uuid

from django.db import models


class UUIDModel(models.Model):
    # UUIDv7 is time-ordered: non-enumerable in URLs while keeping index locality.
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
