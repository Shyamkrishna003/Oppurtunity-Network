from django.contrib import admin

from taxonomy.models import Skill


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "slug", "created_by", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("created_by",)
