import factory
from factory.django import DjangoModelFactory

from apps.organizations.models import OrgRepository, Organization, TeamMembership
from apps.repositories.tests.factories import RepositoryFactory, UserFactory


class OrganizationFactory(DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Org {n}")
    slug = factory.Sequence(lambda n: f"org-{n}")
    description = factory.Faker("sentence")
    github_org_id = None
    owner = factory.SubFactory(UserFactory)


class TeamMembershipFactory(DjangoModelFactory):
    class Meta:
        model = TeamMembership

    organization = factory.SubFactory(OrganizationFactory)
    user = factory.SubFactory(UserFactory)
    role = "member"
    is_active = True


class OrgRepositoryFactory(DjangoModelFactory):
    class Meta:
        model = OrgRepository

    organization = factory.SubFactory(OrganizationFactory)
    repository = factory.SubFactory(RepositoryFactory)
    added_by = factory.SubFactory(UserFactory)
