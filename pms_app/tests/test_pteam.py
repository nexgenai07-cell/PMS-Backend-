from django.urls import reverse
from rest_framework import status

from pms_app.models import PTeam, Project, TeamMember
from .base import BaseAPITestCase


class PTeamListCreateTests(BaseAPITestCase):
    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("pteam-list-create"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_link(self):
        payload = {"p": self.project.p_id, "t": self.task.t_id, "tm": self.team_member.id}
        response = self.client.post(reverse("pteam-list-create"), payload)
        data = self.assertSuccess(response, status.HTTP_201_CREATED)
        self.assertEqual(data["project_name"], "Website Revamp")
        self.assertEqual(data["member_name"], "Ali Raza")

    def test_filter_by_project(self):
        other_project = Project.objects.create(p_name="Other", created_by=self.manager)
        PTeam.objects.create(p=self.project, tm=self.team_member)
        PTeam.objects.create(p=other_project, tm=self.team_member)

        response = self.client.get(reverse("pteam-list-create"), {"project": self.project.p_id})
        data = self.assertSuccess(response)
        self.assertTrue(all(entry["p"] == self.project.p_id for entry in data))

    def test_create_requires_project(self):
        response = self.client.post(reverse("pteam-list-create"), {"tm": self.team_member.id})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)


class PTeamDetailTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.entry = PTeam.objects.create(p=self.project, t=self.task, tm=self.team_member)

    def test_get_existing(self):
        url = reverse("pteam-detail", kwargs={"pt_id": self.entry.pt_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["pt_id"], self.entry.pt_id)

    def test_get_missing_404(self):
        url = reverse("pteam-detail", kwargs={"pt_id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_delete_removes_entry(self):
        url = reverse("pteam-detail", kwargs={"pt_id": self.entry.pt_id})
        self.assertSuccess(self.client.delete(url))
        self.assertFalse(PTeam.objects.filter(pt_id=self.entry.pt_id).exists())
