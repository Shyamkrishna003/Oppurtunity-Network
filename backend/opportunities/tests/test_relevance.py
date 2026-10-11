"""Relevance: the SQL score, the Python explanation, and that the two agree."""

import pytest

from communities.tests.factories import CommunityFactory, CommunityMemberFactory
from opportunities import relevance
from opportunities.models import Opportunity
from opportunities.tests.factories import distribute, make_job
from taxonomy.models import Skill
from users.models import User, UserProfile, UserSkill
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def make_user(*, has=(), interested=(), **profile):
    user = UserFactory()
    for kind, names in (("HAS", has), ("INTERESTED", interested)):
        for skill in Skill.objects.filter(name__in=names):
            UserSkill.objects.create(user=user, skill=skill, kind=kind)
    UserProfile.objects.filter(pk=user.pk).update(**profile)
    # Loaded afresh, so the profile seen by the matcher is the one just written.
    return User.objects.select_related("profile").get(pk=user.pk)


def sql_scores(matcher) -> dict:
    scored = Opportunity.objects.annotate(relevance=relevance.score_expression(matcher))
    return {o.pk: o.relevance for o in scored}


def explained(matcher, opportunity):
    opportunity = Opportunity.objects.prefetch_related("skills").get(pk=opportunity.pk)
    names = relevance.community_names_by_opportunity(matcher, [opportunity.pk])
    return relevance.explain(matcher, opportunity, names.get(opportunity.pk, []))


def kinds(match) -> list[tuple[str, str]]:
    return [(reason["kind"], reason["label"]) for reason in match.reasons]


def test_every_part_of_the_score_and_its_reason():
    user = make_user(
        has=("Python", "Django"),
        interested=("React",),
        city="Kochi",
        country_code="IN",
        work_mode_preference="HYBRID",
    )
    community = CommunityFactory(name="Kochi Developers")
    CommunityMemberFactory(community=community, user=user)
    job = make_job(
        status="PUBLISHED",
        skills=("Python", "Django", "React", "Docker"),
        city="kochi",  # case does not matter
        country_code="IN",
        work_mode="HYBRID",
    )
    distribute(job, community)
    matcher = relevance.load_matcher(user)

    match = explained(matcher, job)

    # 2 skills x5 + 1 interest x3 + community 3 + location 2 + work mode 2
    assert match.score == 20
    assert kinds(match) == [
        ("skill", "Django"),
        ("skill", "Python"),
        ("interest", "React"),
        ("community", "Kochi Developers"),
        ("location", "kochi"),
        ("work_mode", "Hybrid"),
    ]
    assert sql_scores(matcher)[job.pk] == 20


def test_matching_skills_are_capped_so_listing_everything_does_not_win():
    names = ("Python", "Django", "React", "Docker", "PostgreSQL", "Redis")
    user = make_user(has=names, interested=names)
    stuffed = make_job(status="PUBLISHED", skills=names)
    matcher = relevance.load_matcher(user)

    match = explained(matcher, stuffed)

    assert match.score == 4 * 5 + 4 * 3  # four of each count, not six
    assert len(match.reasons) == 12  # but every match is still shown
    assert sql_scores(matcher)[stuffed.pk] == match.score


@pytest.mark.parametrize(
    ("profile", "job_fields", "expected"),
    [
        # A city on the profile: only the same city counts, not merely the same country.
        ({"city": "Kochi", "country_code": "IN"}, {"city": "Kochi", "country_code": "IN"}, 2),
        ({"city": "Kochi", "country_code": "IN"}, {"city": "Chennai", "country_code": "IN"}, 0),
        ({"city": "Kochi", "country_code": "IN"}, {"city": "", "country_code": "IN"}, 0),
        # Only a country on the profile: the same country counts.
        ({"city": "", "country_code": "IN"}, {"city": "Chennai", "country_code": "IN"}, 2),
        ({"city": "", "country_code": "IN"}, {"city": "Berlin", "country_code": "DE"}, 0),
        # Nothing on the profile: a job with no location is not "the same place".
        ({"city": "", "country_code": ""}, {"city": "", "country_code": ""}, 0),
    ],
)
def test_location_rule(profile, job_fields, expected):
    matcher = relevance.load_matcher(make_user(**profile))
    job = make_job(status="PUBLISHED", **job_fields)

    assert explained(matcher, job).score == expected
    assert sql_scores(matcher)[job.pk] == expected


@pytest.mark.parametrize(
    ("share_status", "member_status", "counts"),
    [
        ("APPROVED", "ACTIVE", True),
        ("PENDING", "ACTIVE", False),
        ("REJECTED", "ACTIVE", False),
        ("APPROVED", "INVITED", False),
        ("APPROVED", "LEFT", False),
    ],
)
def test_community_points_need_an_approved_share_and_an_active_membership(
    share_status, member_status, counts
):
    user = UserFactory()
    community = CommunityFactory()
    CommunityMemberFactory(community=community, user=user, status=member_status)
    job = make_job(status="PUBLISHED")
    distribute(job, community, status=share_status)
    matcher = relevance.load_matcher(user)

    assert explained(matcher, job).score == (3 if counts else 0)
    assert sql_scores(matcher)[job.pk] == (3 if counts else 0)


def test_an_empty_profile_scores_everything_zero_with_no_reasons():
    matcher = relevance.load_matcher(UserFactory())
    job = make_job(status="PUBLISHED", city="Kochi", work_mode="REMOTE")

    assert not matcher.has_anything
    assert explained(matcher, job) == relevance.Match(score=0, reasons=[])
    assert sql_scores(matcher)[job.pk] == 0


def test_sql_and_python_agree_across_many_profiles_and_opportunities():
    """The ordering comes from SQL and the explanation from Python; if they ever disagreed,
    the reasons shown would not explain the ranking."""
    communities = [CommunityFactory(), CommunityFactory()]
    skill_sets = [
        (),
        ("Python",),
        ("Python", "Django", "React"),
        ("Python", "Django", "React", "Docker", "PostgreSQL", "Redis"),
        ("Figma", "UX Design"),
    ]
    places = [("Kochi", "IN"), ("KOCHI", "IN"), ("Chennai", "IN"), ("Berlin", "DE"), ("", "")]
    jobs = []
    for index, skills in enumerate(skill_sets):
        for offset, work_mode in enumerate(("REMOTE", "HYBRID", "ONSITE")):
            city, country = places[(index + offset) % len(places)]
            job = make_job(
                status="PUBLISHED",
                skills=skills,
                work_mode=work_mode,
                city=city,
                country_code=country,
            )
            if (index + offset) % 2 == 0:
                distribute(job, communities[offset % 2], status="APPROVED")
            if (index + offset) % 3 == 0:
                distribute(job, communities[(offset + 1) % 2], status="PENDING")
            jobs.append(job)

    users = [
        UserFactory(),
        make_user(has=("Python", "Django"), interested=("React", "Python"), city="Kochi"),
        make_user(has=skill_sets[3], interested=skill_sets[3], country_code="IN"),
        make_user(interested=("Figma",), work_mode_preference="REMOTE", city="Berlin"),
        make_user(has=("Docker",), work_mode_preference="ONSITE", country_code="DE"),
    ]
    CommunityMemberFactory(community=communities[0], user=users[1])
    CommunityMemberFactory(community=communities[1], user=users[2])
    CommunityMemberFactory(community=communities[0], user=users[2])
    CommunityMemberFactory(community=communities[1], user=users[3], status="PENDING")

    for user in users:
        matcher = relevance.load_matcher(user)
        from_sql = sql_scores(matcher)
        for job in jobs:
            assert from_sql[job.pk] == explained(matcher, job).score, (user.email, job.title)
    # The comparison is only meaningful if the scenarios actually differ.
    assert len(set(sql_scores(relevance.load_matcher(users[2])).values())) > 4


def test_loading_the_matcher_and_explaining_a_page_take_a_fixed_number_of_queries(
    django_assert_num_queries,
):
    user = make_user(has=("Python", "Django"), interested=("React",))
    communities = [CommunityFactory() for _ in range(3)]
    for community in communities:
        CommunityMemberFactory(community=community, user=user)
    jobs = [make_job(status="PUBLISHED") for _ in range(6)]
    for job in jobs:
        distribute(job, communities[0])

    with django_assert_num_queries(2):  # skills, communities (the profile is already loaded)
        matcher = relevance.load_matcher(user)
    with django_assert_num_queries(1):
        relevance.community_names_by_opportunity(matcher, [job.pk for job in jobs])
