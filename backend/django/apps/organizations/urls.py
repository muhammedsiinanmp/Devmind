from typing import Any

from django.urls import path

from apps.organizations.views import (
    InviteAcceptView,
    InviteView,
    MemberListView,
    MemberRemoveView,
    OrgCreateView,
    OrgDetailView,
)

urlpatterns: list[Any] = [
    path("", OrgCreateView.as_view(), name="org-create"),
    path("<int:pk>/", OrgDetailView.as_view(), name="org-detail"),
    path("<int:org_pk>/invite/", InviteView.as_view(), name="org-invite"),
    path("<int:org_pk>/members/", MemberListView.as_view(), name="member-list"),
    path(
        "<int:org_pk>/members/<int:user_id>/",
        MemberRemoveView.as_view(),
        name="member-remove",
    ),
    path("invite/accept/", InviteAcceptView.as_view(), name="invite-accept"),
]
