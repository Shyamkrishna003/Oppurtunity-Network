import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from common.pagination import RankedPagination
from communities.tests.factories import CommunityFactory, CommunityMemberFactory
from opportunities.models import Opportunity, SavedOpportunity
from opportunities.tests.factories import distribute, make_job
from organizations.tests.factories import OrganizationFactory, organization_with_roles
from taxonomy.models import Skill
from users.models import UserProfile, UserSkill
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

FEED = "/api/v1/opportunities/"
SAVED = "/api/v1/users/me/saved-opportunities/"


def published(**fields):
    return make_job(status="PUBLISHED", **fields)


def ago(**delta):
    return timezone.now() - timedelta(**delta)


def ahead(**delta):
    return timezone.now() + timedelta(**delta)


def titles(client, **params) -> list[str]:
    response = client.get(FEED, params)
    assert response.status_code == 200, response.json()
    return [item["title"] for item in response.json()["results"]]


def skill_id(name) -> str:
    return str(Skill.objects.get(name=name).pk)


def give_skills(user, *, has=(), interested=()):
    for kind, names in (("HAS", has), ("INTERESTED", interested)):
        for skill in Skill.objects.filter(name__in=names):
            UserSkill.objects.create(user=user, skill=skill, kind=kind)


# --- What the feed contains -------------------------------------------------------------


def test_the_feed_shows_open_opportunities_the_viewer_may_see(api, api_as):
    organization, members = organization_with_roles("MEMBER")
    owner = members["OWNER"].user
    published(title="Public job")
    internal = {"visibility": "ORGANIZATION", "creator": owner, "organization": organization}
    published(title="Internal job", **internal)
    published(title="Hidden by a moderator", moderation_status="HIDDEN")
    make_job(title="My draft", creator=owner)
    make_job(status="CLOSED", title="Closed job")
    make_job(status="EXPIRED", title="Expired job")
    make_job(status="ARCHIVED", title="Archived job")

    assert titles(api) == ["Public job"]
    assert set(titles(api_as(members["MEMBER"].user))) == {"Public job", "Internal job"}
    # Managing something does not put its draft in the feed; that is what "My opportunities" is for.
    assert set(titles(api_as(owner))) == {"Public job", "Internal job"}


def test_a_visitor_gets_no_match_and_a_signed_in_user_gets_reasons(api, api_as):
    user = UserFactory()
    give_skills(user, has=("Python",))
    published(title="Python job", skills=("Python", "Django"), work_mode="REMOTE")

    for_visitor = api.get(FEED).json()["results"][0]
    for_user = api_as(user).get(FEED).json()["results"][0]

    assert (for_visitor["match"], for_visitor["is_saved"]) == (None, False)
    assert for_user["match"] == {"score": 5, "reasons": [{"kind": "skill", "label": "Python"}]}
    assert for_user["job"]["employment_type"] == "FULL_TIME"
    assert [s["name"] for s in for_user["skills"]] == ["Django", "Python"]


# --- Filters ----------------------------------------------------------------------------


def test_filters_narrow_the_feed(api):
    organization = OrganizationFactory()
    owner = UserFactory()
    published(
        title="Kochi senior",
        city="Kochi",
        country_code="IN",
        work_mode="ONSITE",
        skills=("Python",),
        job={"experience_level": "SENIOR"},
    )
    published(
        title="Remote intern",
        work_mode="REMOTE",
        skills=("React",),
        job={"experience_level": "INTERN", "employment_type": "INTERNSHIP"},
    )
    published(
        title="Berlin contract",
        city="Berlin",
        country_code="DE",
        work_mode="HYBRID",
        skills=("Go",),
        creator=owner,
        organization=organization,
        job={"employment_type": "CONTRACT"},
    )

    assert titles(api, type="JOB") == ["Berlin contract", "Remote intern", "Kochi senior"]
    assert titles(api, type="EVENT") == []
    assert titles(api, work_mode="REMOTE") == ["Remote intern"]
    assert titles(api, country="in") == ["Kochi senior"]
    assert titles(api, city="kochi") == ["Kochi senior"]
    assert titles(api, experience_level="SENIOR") == ["Kochi senior"]
    assert titles(api, employment_type="CONTRACT") == ["Berlin contract"]
    assert titles(api, organization=str(organization.pk)) == ["Berlin contract"]
    assert titles(api, organization=str(uuid.uuid7())) == []
    # Filters combine: all must hold.
    assert titles(api, work_mode="REMOTE", experience_level="SENIOR") == []


def test_skill_filter_matches_any_of_the_chosen_skills(api):
    published(title="Python job", skills=("Python", "Django"))
    published(title="React job", skills=("React",))
    published(title="Go job", skills=("Go",))

    both = api.get(f"{FEED}?skill={skill_id('Python')}&skill={skill_id('React')}")

    assert {item["title"] for item in both.json()["results"]} == {"Python job", "React job"}
    assert titles(api, skill=skill_id("Go")) == ["Go job"]
    assert titles(api, skill=str(uuid.uuid7())) == []


def test_date_filters(api):
    published(title="Closing soon", deadline=ahead(days=2), published_at=ago(days=20))
    published(title="Closing later", deadline=ahead(days=30), published_at=ago(days=1))
    published(title="No deadline", published_at=ago(days=40))

    assert titles(api, deadline_before=ahead(days=7).isoformat()) == ["Closing soon"]
    assert titles(api, deadline_after=ahead(days=7).isoformat()) == ["Closing later"]
    assert titles(api, posted_within=7) == ["Closing later"]
    assert titles(api, posted_within=30) == ["Closing later", "Closing soon"]


def test_community_filter_and_my_communities_scope(api, api_as):
    user = UserFactory()
    mine, other = CommunityFactory(), CommunityFactory()
    private = CommunityFactory(visibility="PRIVATE")
    CommunityMemberFactory(community=mine, user=user)
    distribute(published(title="In my community"), mine)
    distribute(published(title="In another community"), other)
    distribute(published(title="Still under review"), mine, status="PENDING")
    distribute(published(title="In a private community"), private)
    published(title="Not shared anywhere")
    client = api_as(user)

    assert titles(client, community=str(mine.pk)) == ["In my community"]
    assert titles(api, community=str(other.pk)) == ["In another community"]
    assert titles(client, scope="communities") == ["In my community"]
    assert titles(api, scope="communities") == []  # a visitor is in no community
    # The job is public, but a filter must not confirm what a private community shows.
    assert titles(client, community=str(private.pk)) == []
    assert "In a private community" in titles(client)


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "popular"},
        {"work_mode": "MOON"},
        {"type": "PARTY"},
        {"skill": "not-a-uuid"},
        {"community": "42"},
        {"posted_within": "0"},
        {"posted_within": "soon"},
        {"country": "India"},
        {"deadline_before": "tomorrow"},
        {"scope": "everything"},
        {"q": "x" * 121},
    ],
)
def test_unknown_filter_values_are_rejected(api, params):
    response = api.get(FEED, params)

    assert response.status_code == 400
    assert list(response.json()["errors"])[0].split(".")[0] == next(iter(params))


# --- Search -----------------------------------------------------------------------------


@pytest.fixture
def searchable():
    labs = OrganizationFactory(name="Example Labs")
    published(
        title="Backend Engineer",
        description="Build APIs with care.",
        skills=("Django",),
        creator=UserFactory(),
        organization=labs,
        city="Kochi",
    )
    published(
        title="Product Designer",
        description="Work with our backend engineers daily.",
        skills=("Figma",),
    )
    published(title="Data Analyst", description="Dashboards and reports.", skills=("SQL",))


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("backend", ["Backend Engineer", "Product Designer"]),  # title outranks description
        ("engineers", ["Backend Engineer", "Product Designer"]),  # word forms
        ("django", ["Backend Engineer"]),  # a skill
        ("example labs", ["Backend Engineer"]),  # the organization
        ("kochi", ["Backend Engineer"]),  # the location
        ("dashboards", ["Data Analyst"]),  # the description
        ('"product designer"', ["Product Designer"]),  # a phrase
        ("backend -designer", ["Backend Engineer"]),  # an exclusion
        ("backend dashboards", []),  # every word must match, and no title is close to this
        ("zebra", []),
    ],
)
def test_search_finds_and_ranks(api, searchable, term, expected):
    assert titles(api, q=term) == expected


@pytest.mark.parametrize("term", ["Bakcend Enginer", "Prodct Desinger", "data analist"])
def test_a_misspelled_search_falls_back_to_similar_titles(api, searchable, term):
    found = titles(api, q=term)

    assert len(found) == 1
    assert found[0] in ("Backend Engineer", "Product Designer", "Data Analyst")


@pytest.mark.parametrize("term", ["%", "_", "'; DROP TABLE opportunities; --", "a & | !", "((("])
def test_search_text_is_never_interpreted_as_a_pattern_or_query(api, searchable, term):
    response = api.get(FEED, {"q": term})

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert Opportunity.objects.count() == 3


def test_search_respects_visibility_and_filters(api, searchable):
    make_job(title="Backend Engineer draft")
    published(title="Backend Engineer hidden", moderation_status="HIDDEN")

    assert titles(api, q="backend") == ["Backend Engineer", "Product Designer"]
    assert titles(api, q="backend", skill=skill_id("Figma")) == ["Product Designer"]


# --- Ordering ---------------------------------------------------------------------------


def test_newest_first_is_the_default_and_deadline_puts_open_ended_last(api):
    published(title="Old, closing first", published_at=ago(days=9), deadline=ahead(days=1))
    published(title="Middle, no deadline", published_at=ago(days=5))
    published(title="New, closing later", published_at=ago(days=1), deadline=ahead(days=9))

    assert titles(api) == ["New, closing later", "Middle, no deadline", "Old, closing first"]
    assert titles(api, sort="newest") == titles(api)
    assert titles(api, sort="deadline") == [
        "Old, closing first",
        "New, closing later",
        "Middle, no deadline",
    ]


def test_most_relevant_orders_by_fit_then_recency(api, api_as):
    user = UserFactory()
    give_skills(user, has=("Python", "Django"), interested=("React",))
    UserProfile.objects.filter(pk=user.pk).update(city="Kochi", work_mode_preference="REMOTE")
    published(title="No fit, newest", skills=("Go",), work_mode="ONSITE", published_at=ago(days=1))
    published(title="Some fit", skills=("Python",), work_mode="ONSITE", published_at=ago(days=3))
    published(
        title="Best fit",
        skills=("Python", "Django", "React"),
        work_mode="REMOTE",
        city="Kochi",
        published_at=ago(days=6),
    )
    published(title="No fit, older", skills=("Go",), work_mode="ONSITE", published_at=ago(days=8))

    response = api_as(user).get(FEED, {"sort": "relevant"}).json()["results"]

    assert [(item["title"], item["match"]["score"]) for item in response] == [
        ("Best fit", 17),
        ("Some fit", 5),
        ("No fit, newest", 0),
        ("No fit, older", 0),
    ]
    # For a visitor there is nothing to match, so it is simply newest first.
    assert titles(api, sort="relevant")[0] == "No fit, newest"


def test_a_search_is_ordered_by_text_match_first_then_by_fit(api_as):
    user = UserFactory()
    give_skills(user, has=("Figma",))
    published(title="Designer", description="Works with a backend team.", skills=("Figma",))
    published(title="Backend Engineer", skills=("Django",))

    found = api_as(user).get(FEED, {"q": "backend"}).json()["results"]

    # The designer job fits the profile better, but the title match on the search term wins.
    assert [item["title"] for item in found] == ["Backend Engineer", "Designer"]
    assert [item["match"]["score"] for item in found] == [0, 5]


def test_most_relevant_without_a_search_looks_at_recent_postings_only(api):
    published(title="Recent", published_at=ago(days=10))
    published(title="Stale", published_at=ago(days=120))

    assert titles(api, sort="relevant") == ["Recent"]
    assert titles(api) == ["Recent", "Stale"]  # browsing by date still shows it
    assert titles(api, q="django", sort="relevant") == ["Recent", "Stale"]  # so does searching


# --- Paging and cost --------------------------------------------------------------------


def page_through(client, **params) -> tuple[list[str], int]:
    """Follow ``next`` links to the end. Returns every title seen and the number of pages."""
    seen, pages, url = [], 0, FEED
    while url:
        body = client.get(url, params if url == FEED else None).json()
        seen += [item["title"] for item in body["results"]]
        pages += 1
        url = body["next"]
    return seen, pages


@pytest.mark.parametrize("sort", ["newest", "deadline", "relevant"])
def test_paging_reaches_every_result_exactly_once(api, sort):
    expected = [f"Job {n:02d}" for n in range(7)]
    for n, title in enumerate(expected):
        published(title=title, published_at=ago(hours=n + 1), deadline=ahead(days=n + 1))

    seen, pages = page_through(api, sort=sort, page_size=3)

    assert seen == expected
    assert pages == 3
    assert "count" not in api.get(FEED, {"sort": sort}).json()


def test_ranked_results_stop_at_the_cap_and_page_size_is_bounded(api, monkeypatch):
    monkeypatch.setattr(RankedPagination, "max_results", 5)
    monkeypatch.setattr(RankedPagination, "max_page_size", 4)
    for n in range(8):
        published(title=f"Job {n}")

    seen, _ = page_through(api, sort="relevant", page_size=100)
    beyond = api.get(FEED, {"sort": "relevant", "offset": 5}).json()
    nonsense = api.get(FEED, {"sort": "relevant", "offset": "-3", "page_size": "lots"})

    assert len(seen) == 5
    assert (beyond["results"], beyond["next"]) == ([], None)
    assert nonsense.status_code == 200


def test_the_feed_takes_a_fixed_number_of_queries(api, api_as, django_assert_max_num_queries):
    user = UserFactory()
    give_skills(user, has=("Python",), interested=("React",))
    community = CommunityFactory()
    CommunityMemberFactory(community=community, user=user)
    for _ in range(12):
        distribute(published(skills=("Python", "React", "Django")), community)
    client = api_as(user)

    with django_assert_max_num_queries(3):
        assert len(api.get(FEED).json()["results"]) == 12
    # Signed in: the user, their skills and communities, the page, its skills, and which of
    # their communities show each result. The same whether there are 12 results or 1200.
    for params in ({}, {"sort": "relevant"}, {"q": "engineer"}, {"scope": "communities"}):
        with django_assert_max_num_queries(8):
            assert len(client.get(FEED, params).json()["results"]) == 12


# --- Saving -----------------------------------------------------------------------------


def test_saving_and_unsaving(api, api_as):
    user = UserFactory()
    job, other = published(title="Keep this"), published(title="Not this")
    client = api_as(user)
    save = f"{FEED}{job.pk}/save/"

    assert client.put(save).status_code == 204
    assert client.put(save).status_code == 204  # saving twice changes nothing
    assert SavedOpportunity.objects.filter(user=user).count() == 1

    assert titles(client, saved="true") == ["Keep this"]
    assert {item["title"]: item["is_saved"] for item in client.get(FEED).json()["results"]} == {
        "Keep this": True,
        "Not this": False,
    }
    assert client.get(f"{FEED}{job.pk}/").json()["viewer"]["is_saved"] is True
    assert client.get(f"{FEED}{other.pk}/").json()["viewer"]["is_saved"] is False
    assert titles(api, saved="true") == []  # nothing is "saved" for a visitor
    assert titles(api_as(UserFactory()), saved="true") == []  # nor by someone else

    assert client.delete(save).status_code == 204
    assert client.delete(save).status_code == 204
    assert titles(client, saved="true") == []


def test_saving_needs_an_account_and_something_the_user_can_see(api, api_as):
    draft = make_job()
    job = published()
    client = api_as(UserFactory())

    assert api.put(f"{FEED}{job.pk}/save/").status_code == 401
    assert client.put(f"{FEED}{draft.pk}/save/").status_code == 404
    assert client.put(f"{FEED}{uuid.uuid7()}/save/").status_code == 404
    assert not SavedOpportunity.objects.exists()


def test_the_saved_list_keeps_closed_ones_but_drops_what_became_invisible(api, api_as):
    user = UserFactory()
    client = api_as(user)
    first, second, third = (published(title=f"Saved {n}") for n in (1, 2, 3))
    for job in (first, second, third):
        client.put(f"{FEED}{job.pk}/save/")
    Opportunity.objects.filter(pk=first.pk).update(status="CLOSED", closed_at=timezone.now())
    Opportunity.objects.filter(pk=second.pk).update(moderation_status="HIDDEN")

    saved = client.get(SAVED).json()["results"]

    # Most recently saved first; a closed job is still worth seeing, a hidden one is not.
    assert [(s["opportunity"]["title"], s["opportunity"]["status"]) for s in saved] == [
        ("Saved 3", "PUBLISHED"),
        ("Saved 1", "CLOSED"),
    ]
    assert saved[0]["saved_at"] is not None
    assert titles(client, saved="true") == ["Saved 3"]  # the feed itself is open ones only
    assert api.get(SAVED).status_code == 401
