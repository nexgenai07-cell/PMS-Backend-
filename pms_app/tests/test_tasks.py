from django.urls import reverse
from rest_framework import status

from pms_app.models import Task, Comment
from .base import BaseAPITestCase


class TaskListCreateTests(BaseAPITestCase):
    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("Create Task View"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_excludes_soft_deleted(self):
        deleted = Task.objects.create(title="Old", p=self.project, created_by=self.manager, is_deleted=True)
        data = self.assertSuccess(self.client.get(reverse("Create Task View")))
        titles = [t["title"] for t in data]
        self.assertIn("Design homepage", titles)
        self.assertNotIn("Old", titles)

    def test_filter_by_status(self):
        Task.objects.create(title="Done Task", p=self.project, created_by=self.manager, status="done")
        response = self.client.get(reverse("Create Task View"), {"status": "done"})
        data = self.assertSuccess(response)
        self.assertTrue(all(t["status"] == "done" for t in data))
        self.assertIn("Done Task", [t["title"] for t in data])

    def test_filter_by_priority(self):
        Task.objects.create(title="Low Prio", p=self.project, created_by=self.manager, priority="low")
        response = self.client.get(reverse("Create Task View"), {"priority": "low"})
        data = self.assertSuccess(response)
        self.assertTrue(all(t["priority"] == "low" for t in data))

    def test_filter_by_project(self):
        from pms_app.models import Project
        other_project = Project.objects.create(p_name="Other", created_by=self.manager)
        Task.objects.create(title="Other Task", p=other_project, created_by=self.manager)
        response = self.client.get(reverse("Create Task View"), {"project": self.project.p_id})
        data = self.assertSuccess(response)
        titles = [t["title"] for t in data]
        self.assertIn("Design homepage", titles)
        self.assertNotIn("Other Task", titles)

    def test_create_sets_created_by_and_assign_by_from_request(self):
        payload = {"title": "New Task", "p": self.project.p_id}
        response = self.client.post(reverse("Create Task View"), payload)
        data = self.assertSuccess(response, status.HTTP_201_CREATED)
        task = Task.objects.get(t_id=data["t_id"])
        self.assertEqual(task.created_by_id, self.manager.id)
        self.assertEqual(task.assign_by_id, self.manager.id)

    def test_create_requires_project(self):
        response = self.client.post(reverse("Create Task View"), {"title": "No project"})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)

    def test_create_requires_title(self):
        response = self.client.post(reverse("Create Task View"), {"p": self.project.p_id})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)

    def test_create_rejects_nonexistent_project(self):
        response = self.client.post(reverse("Create Task View"), {"title": "Ghost", "p": 999999})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)


class TaskDetailTests(BaseAPITestCase):
    def test_get_existing(self):
        url = reverse("TaskDetailView", kwargs={"t_id": self.task.t_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["title"], "Design homepage")

    def test_get_missing_404(self):
        url = reverse("TaskDetailView", kwargs={"t_id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_patch_updates_status(self):
        url = reverse("TaskDetailView", kwargs={"t_id": self.task.t_id})
        data = self.assertSuccess(self.client.patch(url, {"status": "in_progress"}))
        self.assertEqual(data["status"], "in_progress")

    def test_delete_is_soft_delete(self):
        url = reverse("TaskDetailView", kwargs={"t_id": self.task.t_id})
        self.assertSuccess(self.client.delete(url))
        self.task.refresh_from_db()
        self.assertTrue(self.task.is_deleted)
        self.assertTrue(Task.objects.filter(t_id=self.task.t_id).exists())

    def test_deleted_task_not_reachable(self):
        url = reverse("TaskDetailView", kwargs={"t_id": self.task.t_id})
        self.client.delete(url)
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)


class TaskCommentsViewTests(BaseAPITestCase):
    def test_returns_comments_for_task_newest_first(self):
        c1 = Comment.objects.create(t=self.task, u=self.manager, desc="first")
        c2 = Comment.objects.create(t=self.task, u=self.manager, desc="second")
        url = reverse("TaskCommentsView", kwargs={"t_id": self.task.t_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data[0]["c_id"], c2.c_id)
        self.assertEqual(data[1]["c_id"], c1.c_id)

    def test_empty_when_no_comments(self):
        url = reverse("TaskCommentsView", kwargs={"t_id": self.task.t_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data, [])

    def test_does_not_leak_other_tasks_comments(self):
        other_task = Task.objects.create(title="Other", p=self.project, created_by=self.manager)
        Comment.objects.create(t=other_task, u=self.manager, desc="not this one")
        url = reverse("TaskCommentsView", kwargs={"t_id": self.task.t_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data, [])
