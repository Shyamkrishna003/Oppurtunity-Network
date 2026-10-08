"""Enumerations shared by profiles and opportunities, so the two sides can be matched."""

from django.db import models


class WorkMode(models.TextChoices):
    REMOTE = "REMOTE", "Remote"
    HYBRID = "HYBRID", "Hybrid"
    ONSITE = "ONSITE", "On-site"


class ExperienceLevel(models.TextChoices):
    INTERN = "INTERN", "Intern"
    ENTRY = "ENTRY", "Entry"
    MID = "MID", "Mid"
    SENIOR = "SENIOR", "Senior"
    LEAD = "LEAD", "Lead"
