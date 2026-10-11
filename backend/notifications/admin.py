from django.contrib import admin

from notifications.models import Notification, NotificationDelivery


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("created_at", "type", "recipient", "in_app", "read_at")
    list_filter = ("type", "in_app")
    search_fields = ("recipient__email",)
    raw_id_fields = ("recipient", "actor")
    date_hierarchy = "created_at"


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("created_at", "notification", "channel", "status", "attempts", "sent_at")
    list_filter = ("status", "channel")
    raw_id_fields = ("notification",)
