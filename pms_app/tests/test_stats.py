from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from pms_app.models import Project, Task, TeamMember, PTeam, Notification
from .base import BaseAPITestCase


class ProjectStatsViewTests(BaseAPITestCase):
    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        url = reverse("project_stats", kwargs={"p_id": self.project.p_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_project_404(self):
        url = reverse("project_stats", kwargs={"p_id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_project_with_zero_tasks_does_not_divide_by_zero(self):
        empty_project = Project.objects.create(p_name="Empty", created_by=self.manager)
        url = reverse("project_stats", kwargs={"p_id": empty_project.p_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["totalTasks"], 0)
        self.assertEqual(data["completionRate"], 0)
        self.assertEqual(data["onTimeRate"], 0)
        self.assertEqual(data["avgProgress"], 0)

    def test_completion_rate_and_avg_progress_are_computed_correctly(self):
        # self.task ("Design homepage") already exists with status=todo (weight 0)
        Task.objects.create(title="T2", p=self.project, created_by=self.manager, status="in_progress")  # 50
        Task.objects.create(title="T3", p=self.project, created_by=self.manager, status="done")          # 100
        Task.objects.create(title="T4", p=self.project, created_by=self.manager, status="cancelled")     # 0
        # total 4 tasks: weights 0 + 50 + 100 + 0 = 150 / 4 = 37.5
        url = reverse("project_stats", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["totalTasks"], 4)
        self.assertEqual(data["completedTasks"], 1)
        self.assertEqual(data["avgProgress"], 37.5)
        self.assertEqual(data["completionRate"], 25.0)

    def test_excludes_soft_deleted_tasks_from_stats(self):
        Task.objects.create(title="Deleted", p=self.project, created_by=self.manager,
                             status="done", is_deleted=True)
        url = reverse("project_stats", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        # only self.task counts (status=todo) — the deleted "done" task must not
        # be included even though it would raise completionRate if counted.
        self.assertEqual(data["totalTasks"], 1)
        self.assertEqual(data["completedTasks"], 0)

    def test_on_time_rate_only_counts_tasks_with_due_date(self):
        future = timezone.now() + timedelta(days=5)
        Task.objects.create(title="On time", p=self.project, created_by=self.manager,
                             status="done", due_date=future)
        Task.objects.create(title="No due date", p=self.project, created_by=self.manager,
                             status="done")
        url = reverse("project_stats", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        # only 1 of the 2 "done" tasks has a due_date, and it's in the future -> 100%
        self.assertEqual(data["onTimeRate"], 100.0)

    def test_members_count_counts_distinct_team_members(self):
        member2 = TeamMember.objects.create(name="Member 2", added_by=self.manager)
        PTeam.objects.create(p=self.project, tm=self.team_member)
        PTeam.objects.create(p=self.project, tm=self.team_member)  # duplicate on purpose
        PTeam.objects.create(p=self.project, tm=member2)
        url = reverse("project_stats", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["membersCount"], 2)


class TeamMemberStatsViewTests(BaseAPITestCase):
    def test_missing_member_404(self):
        url = reverse("team_member_stats", kwargs={"id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_member_with_no_tasks_returns_zeroes(self):
        lonely = TeamMember.objects.create(name="Lonely", added_by=self.manager)
        url = reverse("team_member_stats", kwargs={"id": lonely.id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["totalTasks"], 0)
        self.assertEqual(data["completionRate"], 0)
        self.assertEqual(data["avgProgress"], 0)

    def test_counts_tasks_via_pteam_link(self):
        PTeam.objects.create(p=self.project, t=self.task, tm=self.team_member)
        url = reverse("team_member_stats", kwargs={"id": self.team_member.id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["totalTasks"], 1)
        self.assertEqual(data["memberName"], "Ali Raza")

    def test_soft_deleted_member_not_found(self):
        self.team_member.is_deleted = 1
        self.team_member.save()
        url = reverse("team_member_stats", kwargs={"id": self.team_member.id})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)


class UserStatsViewTests(BaseAPITestCase):
    def test_missing_user_404(self):
        url = reverse("user_stats", kwargs={"id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_user_with_no_activity_returns_zeroes(self):
        url = reverse("user_stats", kwargs={"id": self.other_user.id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["totalAssignedTasks"], 0)
        self.assertEqual(data["projectsCreated"], 0)
        self.assertEqual(data["commentsCount"], 0)
        self.assertEqual(data["unreadNotifications"], 0)

    def test_counts_projects_created_by_user(self):
        Project.objects.create(p_name="Another one", created_by=self.manager)
        url = reverse("user_stats", kwargs={"id": self.manager.id})
        data = self.assertSuccess(self.client.get(url))
        # self.project + the one just created
        self.assertEqual(data["projectsCreated"], 2)

    def test_unread_notifications_count(self):
        Notification.objects.create(u=self.manager, type="x", message="unread 1")
        Notification.objects.create(u=self.manager, type="x", message="unread 2")
        read_one = Notification.objects.create(u=self.manager, type="x", message="already read")
        read_one.mark_as_read()

        url = reverse("user_stats", kwargs={"id": self.manager.id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["unreadNotifications"], 2)


class ProjectTeamMemberStatsViewTests(BaseAPITestCase):
    def test_missing_project_404(self):
        url = reverse("project_team_stats", kwargs={"p_id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_project_with_no_members_returns_empty_list(self):
        empty_project = Project.objects.create(p_name="No members", created_by=self.manager)
        url = reverse("project_team_stats", kwargs={"p_id": empty_project.p_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["totalMembers"], 0)
        self.assertEqual(data["membersStats"], [])

    def test_returns_stats_per_member_scoped_to_project(self):
        PTeam.objects.create(p=self.project, t=self.task, tm=self.team_member)
        url = reverse("project_team_stats", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["totalMembers"], 1)
        self.assertEqual(data["membersStats"][0]["memberName"], "Ali Raza")
        self.assertEqual(data["membersStats"][0]["totalTasks"], 1)

    def test_does_not_count_members_from_other_projects(self):
        other_project = Project.objects.create(p_name="Other", created_by=self.manager)
        other_member = TeamMember.objects.create(name="Not in this project", added_by=self.manager)
        PTeam.objects.create(p=other_project, tm=other_member)

        url = reverse("project_team_stats", kwargs={"p_id": self.project.p_id})
        data = self.assertSuccess(self.client.get(url))
        names = [m["memberName"] for m in data["membersStats"]]
        self.assertNotIn("Not in this project", names)
