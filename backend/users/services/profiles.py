import io
import uuid
from functools import partial
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from common.errors import BusinessRuleViolation
from taxonomy.models import Skill
from users.models import SkillKind, User, UserBlock, UserProfile, UserSkill

MAX_SKILLS_PER_KIND = 50
MAX_HISTORY_ENTRIES = 30

_AVATAR_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
_AVATAR_MAX_PIXELS = 40_000_000
_AVATAR_SIZE = (512, 512)


def update_profile(profile: UserProfile, changes: dict[str, Any]) -> UserProfile:
    for field, value in changes.items():
        setattr(profile, field, value)
    profile.save(update_fields=[*changes, "updated_at"])
    return profile


def replace_skills(user: User, *, has: list[UUID], interested: list[UUID]) -> None:
    """Make the user's skill sets exactly the given ones."""
    wanted = {(SkillKind.HAS, pk) for pk in has} | {(SkillKind.INTERESTED, pk) for pk in interested}
    known = set(Skill.objects.filter(pk__in={pk for _, pk in wanted}).values_list("pk", flat=True))
    unknown = sorted(str(pk) for _, pk in wanted if pk not in known)
    if unknown:
        raise BusinessRuleViolation(
            "Some skills do not exist.", code="unknown_skill", errors={"skills": unknown}
        )

    with transaction.atomic():
        # Lock the user row so two concurrent replacements cannot interleave.
        User.objects.select_for_update().get(pk=user.pk)
        current = {
            (SkillKind(kind), pk)
            for kind, pk in UserSkill.objects.filter(user=user).values_list("kind", "skill_id")
        }
        for kind, pk in current - wanted:
            UserSkill.objects.filter(user=user, kind=kind, skill_id=pk).delete()
        UserSkill.objects.bulk_create(
            UserSkill(user=user, kind=kind, skill_id=pk) for kind, pk in wanted - current
        )


def _encode_avatar(upload: UploadedFile[Any]) -> bytes:
    """Validate by decoding, then re-encode: the stored bytes are ours, without metadata."""
    invalid = BusinessRuleViolation(
        "Upload a JPEG, PNG or WebP image.",
        code="invalid_image",
        errors={"file": ["Upload a JPEG, PNG or WebP image."]},
    )
    if upload.size is None or upload.size > settings.AVATAR_MAX_BYTES:
        limit_mb = settings.AVATAR_MAX_BYTES // (1024 * 1024)
        message = f"The image must be {limit_mb} MB or smaller."
        raise BusinessRuleViolation(message, code="file_too_large", errors={"file": [message]})
    try:
        with Image.open(upload) as image:
            # Header checks first: format by content (not filename or client MIME type), and
            # a pixel cap so a small file cannot expand into gigabytes when decoded.
            if image.format not in _AVATAR_FORMATS:
                raise invalid
            if image.width * image.height > _AVATAR_MAX_PIXELS:
                raise invalid
            oriented = ImageOps.exif_transpose(image)
            has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
            result = oriented.convert("RGBA" if has_alpha else "RGB")
            result.thumbnail(_AVATAR_SIZE)
            buffer = io.BytesIO()
            result.save(buffer, format="WEBP", quality=85)
            return buffer.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise invalid from exc


def _delete_stored_file(name: str) -> None:
    default_storage.delete(name)


def set_avatar(profile: UserProfile, upload: UploadedFile[Any]) -> UserProfile:
    content = _encode_avatar(upload)
    previous = profile.avatar
    # Random key: not guessable from the user and never derived from the uploaded filename.
    name = default_storage.save(f"avatars/{uuid.uuid4().hex}.webp", ContentFile(content))
    with transaction.atomic():
        profile.avatar = name
        profile.save(update_fields=["avatar", "updated_at"])
        if previous:
            transaction.on_commit(partial(_delete_stored_file, previous))
    return profile


def remove_avatar(profile: UserProfile) -> UserProfile:
    previous = profile.avatar
    if not previous:
        return profile
    with transaction.atomic():
        profile.avatar = ""
        profile.save(update_fields=["avatar", "updated_at"])
        transaction.on_commit(partial(_delete_stored_file, previous))
    return profile


def block_user(*, blocker: User, blocked: User) -> None:
    if blocker.pk == blocked.pk:
        raise BusinessRuleViolation("You cannot block yourself.", code="cannot_block_self")
    # Idempotent; the unique constraint settles concurrent duplicates.
    UserBlock.objects.get_or_create(blocker=blocker, blocked=blocked)


def unblock_user(*, blocker: User, blocked_id: UUID) -> None:
    UserBlock.objects.filter(blocker=blocker, blocked_id=blocked_id).delete()
