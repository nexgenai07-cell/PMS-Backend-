"""
Regression tests for defects found during code review.

Every test in this file documents ONE concrete, provable bug in the current
implementation. They are written against the *correct* expected behaviour
(per the README and normal REST semantics), NOT against whatever the buggy
code currently does — so, per the project owner's request, these tests exist
specifically to catch backend issues rather than to rubber-stamp them.

Until the underlying code is fixed, the tests in this file are EXPECTED TO
FAIL. That is the point: a red test here is a confirmed, reproducible bug
report, not a broken test.

Each test's docstring explains: what's wrong, where, and what the fix is.
"""
from django.urls import reverse
from rest_framework import status

from .base import BaseAPITestCase


class TaskFilterByAssignedMemberBugTests(BaseAPITestCase):
    def test_filtering_tasks_by_assign_to_should_work(self):
        """
        BUG: pms_app/views.py -> TaskListCreateView.get()
            tasks.filter(assign_to__u_id=assigned_to)
        `TeamMember` has no `u_id` field (its PK is `id`). Filtering tasks by
        `?assign_to=<team_member_id>` currently raises a FieldError (500)
        instead of returning the matching tasks.
        FIX: change the lookup to `assign_to__id=assigned_to`.
        """
        response = self.client.get(reverse("Create Task View"), {"assign_to": self.team_member.id})
        self.assertEqual(
            response.status_code, status.HTTP_200_OK,
            "Filtering tasks by assign_to currently errors out — "
            "TaskListCreateView uses the non-existent lookup assign_to__u_id.",
        )
        data = response.data["data"]
        self.assertIn("Design homepage", [t["title"] for t in data])


class TaskListSerializerAssigneeNameBugTests(BaseAPITestCase):
    def test_task_list_exposes_correct_assignee_name(self):
        """
        BUG: pms_app/serializers.py -> TaskListSerializer
            assign_to_name = serializers.CharField(source="assign_to.u_name", read_only=True)
        `TeamMember` has no `u_name` field (that field only exists on `User`);
        the member's display name lives in `TeamMember.name`. As written this
        either raises an AttributeError while serializing or silently
        returns nothing useful for every task in the list endpoint.
        FIX: source should be "assign_to.name".
        """
        response = self.client.get(reverse("Create Task View"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.data["data"]
        task_row = next(t for t in data if t["t_id"] == self.task.t_id)
        self.assertEqual(
            task_row.get("assign_to_name"), "Ali Raza",
            "TaskListSerializer.assign_to_name is wired to TeamMember.u_name, "
            "which doesn't exist — it should read TeamMember.name.",
        )


class NotificationMarkAllReadRoutingBugTests(BaseAPITestCase):
    def test_mark_all_read_works_without_requiring_a_notification_id(self):
        """
        BUG: pms_api/urls.py
            path('api/notifications/<n_id>/read-all', NotificationMarkAllReadView.as_view(), ...)
        This route requires an `<n_id>` URL segment, but
        NotificationMarkAllReadView.patch(self, request) takes no such
        argument — calling this endpoint raises a TypeError (500) instead of
        marking all of the user's notifications as read, as documented in
        the README (`PATCH /api/notifications/read-all/`).
        FIX: the URL should be `api/notifications/read-all` with no id
        segment, matching the view signature and the README.
        """
        from pms_app.models import Notification
        Notification.objects.create(u=self.manager, type="x", message="one")
        Notification.objects.create(u=self.manager, type="x", message="two")

        url = "/api/notifications/read-all"
        response = self.client.patch(url)
        self.assertEqual(
            response.status_code, status.HTTP_200_OK,
            "PATCH /api/notifications/read-all should mark all of the "
            "current user's notifications as read without needing an id "
            "in the URL.",
        )
        unread_left = Notification.objects.filter(u=self.manager, is_read=False).count()
        self.assertEqual(unread_left, 0)


class UserAccountAuthorizationBugTests(BaseAPITestCase):
    def test_a_regular_user_cannot_delete_someone_elses_account(self):
        """
        BUG: pms_app/views.py -> UserDetailView.delete()
        There is no ownership/role check at all: ANY authenticated user can
        soft-delete or edit ANY other user's account by id, including admins.
        FIX: only allow a user to modify their own account, or an admin to
        modify any account (e.g. `if request.user.id != id and
        request.user.role != "admin": return error(..., 403)`).
        """
        self.as_user(self.other_user)  # a plain, unrelated authenticated user
        url = reverse("Single_User", kwargs={"id": self.manager.id})
        response = self.client.delete(url)
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Any authenticated user can currently delete any other user's "
            "account — UserDetailView has no ownership/role check.",
        )
        self.manager.refresh_from_db()
        self.assertFalse(self.manager.is_deleted)
