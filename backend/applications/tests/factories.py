import uuid

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from applications.models import Application, ApplicationStatusHistory
from common.storage import private_storage
from opportunities.tests.factories import make_job
from users.tests.factories import UserFactory

PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def pdf(name="resume.pdf", content=PDF, content_type="application/pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


def make_application(*, status="APPLIED", opportunity=None, applicant=None, **fields):
    """An application in the given state, with a stored resume.

    Rows are written directly (not through the services), so tests can start from any state.
    """
    opportunity = opportunity or make_job(status="PUBLISHED")
    applicant = applicant or UserFactory()
    key = private_storage().save(f"resumes/{uuid.uuid4().hex}.pdf", ContentFile(PDF))
    application = Application.objects.create(
        opportunity=opportunity,
        applicant=applicant,
        status=status,
        resume=key,
        status_changed_at=timezone.now(),
        **fields,
    )
    ApplicationStatusHistory.objects.create(
        application=application, to_status="APPLIED", actor=applicant
    )
    if status != "APPLIED":
        ApplicationStatusHistory.objects.create(
            application=application, from_status="APPLIED", to_status=status
        )
    return application
