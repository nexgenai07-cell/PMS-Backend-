from django.urls import reverse
from rest_framework import status

from pms_app.models import Project, Task
from .base import BaseAPITestCase


class ProjectListCreateTests(BaseAPITestCase):
    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("project_list_CR"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_excludes_soft_deleted(self):
        deleted = Project.objects.create(p_name="Old Project", created_by=self.manager, is_deleted=True)
        response = self.client.get(reverse("project_list_CR"))
        data = self.assertSuccess(response)
        names = [p["p_name"] for p in data]
        self.assertIn("Website Revamp", names)
        self.assertNotIn("Old Project", names)

    def test_list_ordered_newest_first(self):
        Project.objects.create(p_name="Second Project", created_by=self.manager)
        response = self.client.get(reverse("project_list_CR"))
        data = self.assertSuccess(response)
        self.assertEqual(data[0]["p_name"], "Second Project")

    def test_create_project_sets_creator_from_request(self):
        payload = {"p_name": "Mobile App", "priority": "critical"}
        response = self.client.post(reverse("project_list_CR"), payload)
        data = self.assertSuccess(response, status.HTTP_201_CREATED)
        project = Project.objects.get(p_id=data["p_id"])
        self.assertEqual(project.created_by_id, self.manager.id)

    def test_create_requires_name(self):
        response = self.client.post(reverse("project_list_CR"), {"desc": "no name given"})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)

    def test_create_rejects_invalid_priority(self):
        response = self.client.post(reverse("project_list_CR"), {"p_name": "X", "priority": "urgent!"})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)

    def test_default_status_is_planning(self):
        response = self.client.post(reverse("project_list_CR"), {"p_name": "Default Status Project"})
        data = self.assertSuccess(response, status.HTTP_201_CREATED)
        self.assertEqual(data["status"], "planning")


class ProjectDetailTests(BaseAPITestCase):
    def test_get_existing(self):
        url = reverse("project_details_view_UD", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["p_name"], "Website Revamp")

    def test_get_missing_404(self):
        url = reverse("project_details_view_UD", kwargs={"p_id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_patch_updates_status(self):
        url = reverse("project_details_view_UD", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.patch(url, {"status": "completed"}))
        self.assertEqual(data["status"], "completed")

    def test_delete_is_soft_delete_and_keeps_tasks(self):
        url = reverse("project_details_view_UD", kwargs={"p_id": self.project.p_id})
        self.assertSuccess(self.client.delete(url))
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_deleted)
        # tasks should still physically exist (soft delete, not CASCADE)
        self.assertTrue(Task.objects.filter(t_id=self.task.t_id).exists())


class ProjectTasksViewTests(BaseAPITestCase):
    def test_returns_only_tasks_for_that_project(self):
        other_project = Project.objects.create(p_name="Unrelated", created_by=self.manager)
        Task.objects.create(title="Unrelated Task", p=other_project, created_by=self.manager)

        url = reverse("ProjectTasksView", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        titles = [t["title"] for t in data]
        self.assertIn("Design homepage", titles)
        self.assertNotIn("Unrelated Task", titles)

    def test_excludes_soft_deleted_tasks(self):
        self.task.soft_delete()
        url = reverse("ProjectTasksView", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data, [])

    def test_empty_project_returns_empty_list(self):
        empty_project = Project.objects.create(p_name="No Tasks Yet", created_by=self.manager)
        url = reverse("ProjectTasksView", kwargs={"p_id": empty_project.p_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data, [])
