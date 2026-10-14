from uuid import UUID

from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics import funnels, policies, selectors
from analytics.api import serializers
from audit.api.views import IsPlatformAdmin
from communities import selectors as communities
from communities.policies import actor_for
from communities.policies import can_manage as can_manage_community
from opportunities import selectors as opportunities
from opportunities.models import Opportunity, OpportunityStatus
from opportunities.policies import can_manage, can_post_for
from organizations import selectors as organizations
from users.api.utils import current_user

DAYS_SHOWN = 14
TOP_SHOWN = 5


class PlatformTotalsView(APIView):
    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses=serializers.PlatformTotalsSerializer)
    def get(self, request: Request) -> Response:
        """Counts across the platform, for its admins. Up to a minute old."""
        return Response(serializers.PlatformTotalsSerializer(selectors.platform_totals()).data)


class OpportunityNumbersView(APIView):
    @extend_schema(responses=serializers.OpportunityNumbersSerializer)
    def get(self, request: Request, opportunity_id: UUID) -> Response:
        """How an opportunity is doing, counted now. For the people who manage it: 404 if
        the caller cannot see it, 403 if they can but do not manage it."""
        user = current_user(request)
        opportunity = opportunities.get_opportunity(user, opportunity_id)
        membership = opportunities.get_membership(user, opportunity.organization_id)
        if not can_manage(user, opportunity, membership):
            raise PermissionDenied()
        numbers = selectors.numbers_for([opportunity.pk])[opportunity.pk]
        data = {
            **numbers,
            "popularity_score": policies.popularity(
                **{name: value for name, value in numbers.items() if name != "views"}
            ),
            "views_by_day": [
                {"date": day, "views": views}
                for day, views in selectors.views_by_day(opportunity.pk, DAYS_SHOWN)
            ],
            "funnels": funnels.as_data(
                funnels.for_opportunities(Opportunity.objects.filter(pk=opportunity.pk))
            ),
        }
        return Response(serializers.OpportunityNumbersSerializer(data).data)


class OrganizationNumbersView(APIView):
    @extend_schema(responses=serializers.OrganizationNumbersSerializer)
    def get(self, request: Request, organization_id: UUID) -> Response:
        """How everything the organization posted is doing. For its owners, admins and
        recruiters: the people who can already see each of those opportunities' numbers."""
        user = current_user(request)
        organization = organizations.get_organization(user, organization_id)
        if not can_post_for(organizations.get_membership(user, organization)):
            raise PermissionDenied()
        posted = Opportunity.objects.filter(organization=organization)
        S = OpportunityStatus
        data = {
            "opportunities": posted.aggregate(
                drafts=Count("pk", filter=Q(status=S.DRAFT)),
                published=Count("pk", filter=Q(status=S.PUBLISHED)),
                finished=Count("pk", filter=Q(status__in=(S.CLOSED, S.EXPIRED, S.ARCHIVED))),
            ),
            "funnels": funnels.as_data(funnels.for_opportunities(posted)),
            "top": [
                {
                    "id": stats.opportunity_id,
                    "title": stats.opportunity.title,
                    "type": stats.opportunity.type,
                    "views": stats.views,
                    "applications": stats.applications,
                    "registrations": stats.registrations,
                }
                for stats in selectors.most_popular(posted, TOP_SHOWN)
            ],
        }
        return Response(serializers.OrganizationNumbersSerializer(data).data)


class CommunityNumbersView(APIView):
    @extend_schema(responses=serializers.CommunityNumbersSerializer)
    def get(self, request: Request, community_id: UUID) -> Response:
        """How the community is doing: members, what it shows, and reports waiting. For
        its owners and admins."""
        user = current_user(request)
        community = communities.get_community(user, community_id)
        actor = actor_for(user.pk, communities.get_membership(user, community))
        if not can_manage_community(actor):
            raise PermissionDenied()
        return Response(
            serializers.CommunityNumbersSerializer(funnels.community_numbers(community)).data
        )
