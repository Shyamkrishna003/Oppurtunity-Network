"""Fill a throwaway database with enough made-up data to measure query plans and load.

    DATABASE_URL=postgres://…/opportunity_perf python manage.py seed_load

Refuses to run against anything that does not look disposable. The data is not meant to
look real, only to be shaped like real data: skewed towards recent postings, a few big
communities, most people with a handful of skills.
"""

import random
from datetime import timedelta
from typing import Any

from django.contrib.auth.hashers import make_password
from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from django.utils import timezone

from applications.models import Application, ApplicationStatusHistory
from communities.models import Community, CommunityMember
from events.models import EventDetail
from jobs.models import JobDetail
from notifications.models import Notification
from opportunities.models import (
    Opportunity,
    OpportunityCommunity,
    OpportunitySkill,
    SavedOpportunity,
)
from organizations.models import Organization, OrganizationMember
from taxonomy.models import Skill
from users.models import User, UserProfile, UserSkill

# Part of the database's name must say it is safe to fill with rubbish.
DISPOSABLE = ("perf", "load", "scratch")
PASSWORD = "correct-horse-battery"  # noqa: S105 - made-up accounts in a throwaway database
CITIES = [
    ("IN", "Kochi"),
    ("IN", "Bengaluru"),
    ("IN", "Mumbai"),
    ("DE", "Berlin"),
    ("US", "Austin"),
]
ROLES = [
    "Backend Engineer", "Frontend Developer", "Data Analyst", "Product Designer",
    "DevOps Engineer", "QA Engineer", "Mobile Developer", "Support Specialist",
]  # fmt: skip
WORDS = [
    "build", "ship", "scale", "design", "review", "mentor", "python", "django", "react",
    "postgres", "team", "remote", "growth", "platform", "data", "product", "customers",
]  # fmt: skip
BATCH = 2000


class Command(BaseCommand):
    help = "Fill a disposable database with a large amount of made-up data."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--users", type=int, default=5000)
        parser.add_argument("--opportunities", type=int, default=30000)

    def handle(self, *args: Any, **options: Any) -> None:
        name = connection.settings_dict["NAME"]
        if not any(word in name for word in DISPOSABLE):
            raise CommandError(
                f'Refusing to fill "{name}": its name must contain one of {DISPOSABLE}. '
                "Create a separate database for this."
            )
        if User.objects.exists():
            raise CommandError(f'"{name}" already has users. Seed an empty database.')

        rng = random.Random(42)  # noqa: S311 - reproducible made-up data, not security
        now = timezone.now()
        with transaction.atomic():
            users = self._users(options["users"], rng)
            skills = list(Skill.objects.all())
            self._user_skills(users, skills, rng)
            organizations = self._organizations(users, rng, now)
            communities = self._communities(users, rng, now)
            opportunities = self._opportunities(
                options["opportunities"], users, organizations, skills, rng, now
            )
            self._shares(opportunities, communities, rng)
            self._activity(opportunities, users, rng, now)
        self.stdout.write(
            f"{len(users)} users, {len(organizations)} organizations, {len(communities)} "
            f"communities, {len(opportunities)} opportunities in {name}. "
            f"Everyone's password is {PASSWORD}; sign in as load-0@example.com."
        )

    def _users(self, count: int, rng: random.Random) -> list[User]:
        hashed = make_password(PASSWORD)
        now = timezone.now()
        users = User.objects.bulk_create(
            [
                User(email=f"load-{n}@example.com", password=hashed, email_verified_at=now)
                for n in range(count)
            ],
            batch_size=BATCH,
        )
        profiles = []
        for n, user in enumerate(users):
            country, city = rng.choice(CITIES)
            profiles.append(
                UserProfile(
                    user=user,
                    display_name=f"Load User {n}",
                    country_code=country,
                    city=city,
                    work_mode_preference=rng.choice(["REMOTE", "HYBRID", "ONSITE", ""]),
                )
            )
        UserProfile.objects.bulk_create(profiles, batch_size=BATCH)
        return users

    def _user_skills(self, users: list[User], skills: list[Skill], rng: random.Random) -> None:
        rows = []
        for user in users:
            for skill in rng.sample(skills, 5):
                rows.append(
                    UserSkill(user=user, skill=skill, kind=rng.choice(["HAS", "HAS", "INTERESTED"]))
                )
        UserSkill.objects.bulk_create(rows, batch_size=BATCH, ignore_conflicts=True)

    def _organizations(self, users: list[User], rng: random.Random, now: Any) -> list[Organization]:
        organizations = Organization.objects.bulk_create(
            [Organization(name=f"Load Org {n}", slug=f"load-org-{n}") for n in range(300)]
        )
        members = []
        for n, organization in enumerate(organizations):
            # The first users own one organization each, so load-0 has something to manage.
            people = [users[n], *rng.sample(users[300:], 8)]
            for index, user in enumerate(people):
                role = "OWNER" if index == 0 else rng.choice(["ADMIN", "RECRUITER", "MEMBER"])
                members.append(
                    OrganizationMember(
                        organization=organization,
                        user=user,
                        role=role,
                        status="ACTIVE",
                        joined_at=now,
                    )
                )
        OrganizationMember.objects.bulk_create(members, batch_size=BATCH, ignore_conflicts=True)
        return organizations

    def _communities(self, users: list[User], rng: random.Random, now: Any) -> list[Community]:
        communities = Community.objects.bulk_create(
            [
                Community(
                    name=f"Load Community {n}",
                    slug=f"load-community-{n}",
                    join_policy="OPEN",
                    posting_policy="MEMBERS_AUTO",
                    visibility="PRIVATE" if n % 10 == 0 else "PUBLIC",
                )
                for n in range(200)
            ]
        )
        members = []
        for n, community in enumerate(communities):
            # A few very large communities, many small ones.
            size = 2000 if n < 5 else rng.randint(20, 200)
            people = rng.sample(users, min(size, len(users)))
            if n < 20 and users[0] not in people:
                people[0] = users[0]
            for index, user in enumerate(people):
                members.append(
                    CommunityMember(
                        community=community,
                        user=user,
                        role="OWNER" if index == 0 else "MEMBER",
                        status="ACTIVE",
                        joined_at=now,
                    )
                )
        CommunityMember.objects.bulk_create(members, batch_size=BATCH, ignore_conflicts=True)
        return communities

    def _opportunities(
        self,
        count: int,
        users: list[User],
        organizations: list[Organization],
        skills: list[Skill],
        rng: random.Random,
        now: Any,
    ) -> list[Opportunity]:
        opportunities, chosen = [], []
        for n in range(count):
            country, city = rng.choice(CITIES)
            is_event = n % 7 == 0
            organization = rng.choice(organizations) if n % 4 else None
            # Most are open; some are drafts or finished, as in a database that has a past.
            status = rng.choices(["PUBLISHED", "DRAFT", "CLOSED", "EXPIRED"], [80, 5, 10, 5])[0]
            # Skewed to the recent past: half within the last three weeks.
            age = timedelta(days=min(rng.expovariate(1 / 30), 400))
            picked = rng.sample(skills, 3)
            chosen.append(picked)
            opportunities.append(
                Opportunity(
                    type="EVENT" if is_event else "JOB",
                    creator=users[n % len(users)],
                    organization=organization,
                    title=f"{rng.choice(ROLES)} {'meetup' if is_event else ''} {n}".replace(
                        "  ", " "
                    ),
                    description=" ".join(rng.choices(WORDS, k=60)),
                    status=status,
                    visibility=rng.choices(["PUBLIC", "COMMUNITY"], [85, 15])[0],
                    work_mode=rng.choice(["REMOTE", "HYBRID", "ONSITE"]),
                    country_code=country,
                    city=city,
                    deadline=None
                    if is_event or n % 3
                    else now + timedelta(days=rng.randint(1, 60)),
                    published_at=None if status == "DRAFT" else now - age,
                    closed_at=now if status in ("CLOSED", "EXPIRED") else None,
                    close_reason="FILLED" if status == "CLOSED" else "",
                    skills_text=" ".join(sorted(skill.name for skill in picked)),
                )
            )
        opportunities = Opportunity.objects.bulk_create(opportunities, batch_size=BATCH)

        OpportunitySkill.objects.bulk_create(
            [
                OpportunitySkill(opportunity=opportunity, skill=skill)
                for opportunity, picked in zip(opportunities, chosen, strict=True)
                for skill in picked
            ],
            batch_size=BATCH,
        )
        jobs = [o for o in opportunities if o.type == "JOB"]
        JobDetail.objects.bulk_create(
            [
                JobDetail(
                    opportunity=job,
                    employment_type=rng.choice(["FULL_TIME", "PART_TIME", "CONTRACT"]),
                    experience_level=rng.choice(["ENTRY", "MID", "SENIOR"]),
                )
                for job in jobs
            ],
            batch_size=BATCH,
        )
        EventDetail.objects.bulk_create(
            [
                EventDetail(
                    opportunity=event,
                    event_status="REGISTRATION_OPEN" if event.status == "PUBLISHED" else "",
                    format="IN_PERSON",
                    start_at=now + timedelta(days=rng.randint(2, 90)),
                    end_at=now + timedelta(days=91),
                    timezone="Asia/Kolkata",
                    venue="Somewhere",
                    capacity=rng.choice([None, 50, 200]),
                )
                for event in opportunities
                if event.type == "EVENT"
            ],
            batch_size=BATCH,
        )
        # One statement for every row, the same weights as opportunities.search.reindex.
        Opportunity.objects.update(
            search_vector=SearchVector("title", weight="A", config="english")
            + SearchVector("skills_text", weight="B", config="english")
            + SearchVector("city", weight="C", config="english")
            + SearchVector("description", weight="D", config="english")
        )
        return opportunities

    def _shares(
        self, opportunities: list[Opportunity], communities: list[Community], rng: random.Random
    ) -> None:
        rows = []
        for n, opportunity in enumerate(opportunities):
            if opportunity.status == "DRAFT" or (n % 2 and opportunity.visibility == "PUBLIC"):
                continue
            for community in rng.sample(communities[:40] + communities, 2):
                rows.append(
                    OpportunityCommunity(
                        opportunity=opportunity,
                        community=community,
                        status=rng.choices(["APPROVED", "PENDING", "REJECTED"], [85, 10, 5])[0],
                    )
                )
        OpportunityCommunity.objects.bulk_create(rows, batch_size=BATCH, ignore_conflicts=True)

    def _activity(
        self, opportunities: list[Opportunity], users: list[User], rng: random.Random, now: Any
    ) -> None:
        jobs = [o for o in opportunities if o.type == "JOB" and o.status == "PUBLISHED"]
        applications = []
        # A few jobs with long pipelines, the rest with a few applicants or none.
        for n, job in enumerate(jobs[:4000]):
            for applicant in rng.sample(users, 400 if n < 5 else rng.randint(0, 12)):
                applications.append(
                    Application(
                        opportunity=job,
                        applicant=applicant,
                        status=rng.choice(
                            ["APPLIED", "APPLIED", "SCREENING", "INTERVIEW", "REJECTED"]
                        ),
                        resume="resumes/seed.pdf",
                        status_changed_at=now,
                    )
                )
        applications = Application.objects.bulk_create(
            applications, batch_size=BATCH, ignore_conflicts=True
        )
        ApplicationStatusHistory.objects.bulk_create(
            [
                ApplicationStatusHistory(
                    application=a, to_status="APPLIED", actor_id=a.applicant_id
                )
                for a in applications
            ],  # fmt: skip
            batch_size=BATCH,
        )
        SavedOpportunity.objects.bulk_create(
            [
                SavedOpportunity(user=rng.choice(users[:500]), opportunity=o)
                for o in rng.sample(jobs, 5000)
            ],  # fmt: skip
            batch_size=BATCH,
            ignore_conflicts=True,
        )
        # One person with a very long notification history, most with a little.
        notifications = []
        for n, user in enumerate(users[:1000]):
            for index in range(3000 if n == 0 else rng.randint(0, 40)):
                notifications.append(
                    Notification(
                        recipient=user,
                        type="APPLICATION_ADVANCED",
                        target_type="applications.application",
                        target_id=jobs[index % len(jobs)].pk,
                        # Everything the renderer for this type reads.
                        payload={
                            "application_id": str(jobs[index % len(jobs)].pk),
                            "opportunity_title": "Seeded",
                            "status": "INTERVIEW",
                            "status_label": "Interview",
                        },
                        read_at=None if index % 3 else now,
                    )
                )
        Notification.objects.bulk_create(notifications, batch_size=BATCH)
