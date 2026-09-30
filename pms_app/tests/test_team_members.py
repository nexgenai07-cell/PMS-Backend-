from django.urls import reverse
from rest_framework import status

from pms_app.models import TeamMember
from .base import BaseAPITestCase


class TeamMemberListCreateTests(BaseAPITestCase):
    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("team_member_list_CR"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_excludes_soft_deleted(self):
        deleted = TeamMember.objects.create(name="Ghost", added_by=self.manager, is_deleted=1)
        response = self.client.get(reverse("team_member_list_CR"))
        data = self.assertSuccess(response)
        names = [m["name"] for m in data]
        self.assertIn("Ali Raza", names)
        self.assertNotIn("Ghost", names)

    def test_list_is_sorted_by_name(self):
        TeamMember.objects.create(name="Zara", added_by=self.manager)
        TeamMember.objects.create(name="Adnan", added_by=self.manager)
        response = self.client.get(reverse("team_member_list_CR"))
        data = self.assertSuccess(response)
        names = [m["name"] for m in data]
        self.assertEqual(names, sorted(names))

    def test_create_team_member(self):
        payload = {"name": "New Dev", "skills": "Go,Rust", "role": "Developer", "experience": 2}
        response = self.client.post(reverse("team_member_list_CR"), payload)
        data = self.assertSuccess(response, status.HTTP_201_CREATED)
        self.assertEqual(data["name"], "New Dev")

    def test_added_by_is_set_from_request_user_not_client(self):
        """added_by is a read_only_field — a client-supplied value must be ignored,
        and the real request.user should be recorded instead."""
        payload = {"name": "Sneaky", "added_by": self.other_user.id}
        response = self.client.post(reverse("team_member_list_CR"), payload)
        data = self.assertSuccess(response, status.HTTP_201_CREATED)
        member = TeamMember.objects.get(id=data["id"])
        self.assertEqual(member.added_by_id, self.manager.id)

    def test_create_requires_name(self):
        response = self.client.post(reverse("team_member_list_CR"), {"skills": "Nothing"})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)


class TeamMemberDetailTests(BaseAPITestCase):
    def test_get_existing(self):
        url = reverse("team_memebr_details_view_UD", kwargs={"id": self.team_member.id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["name"], "Ali Raza")

    def test_get_missing_404(self):
        url = reverse("team_memebr_details_view_UD", kwargs={"id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_patch_updates_fields(self):
        url = reverse("team_memebr_details_view_UD", kwargs={"id": self.team_member.id})
        data = self.assertSuccess(self.client.patch(url, {"experience": 7}))
        self.assertEqual(data["experience"], 7)

    def test_delete_is_soft_delete(self):
        url = reverse("team_memebr_details_view_UD", kwargs={"id": self.team_member.id})
        self.assertSuccess(self.client.delete(url))
        self.team_member.refresh_from_db()
        self.assertEqual(self.team_member.is_deleted, 1)
        self.assertTrue(TeamMember.objects.filter(id=self.team_member.id).exists())

    def test_deleted_member_no_longer_reachable_via_detail(self):
        url = reverse("team_memebr_details_view_UD", kwargs={"id": self.team_member.id})
        self.client.delete(url)
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)
