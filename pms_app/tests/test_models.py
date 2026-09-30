"""
Model-level unit tests — no HTTP layer involved.
Covers default values, soft-delete helpers, __str__ methods and the
Notification.mark_as_read() helper.
"""
from django.test import TestCase
from django.utils import timezone

from pms_app.models import User, TeamMember, Project, Task, Comment, Notification, PTeam


class UserModelTests(TestCase):
    def test_create_user_hashes_password(self):
        user = User.objects.create_user(email="a@test.com", u_name="A", password="secret123")
        self.assertNotEqual(user.password, "secret123")
        self.assertTrue(user.check_password("secret123"))

    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", u_name="No Email", password="secret123")

    def test_email_is_normalized(self):
        user = User.objects.create_user(email="Test@EXAMPLE.com", u_name="T", password="secret123")
        self.assertEqual(user.email, "Test@example.com")

    def test_create_superuser_sets_flags(self):
        admin = User.objects.create_superuser(email="root@test.com", u_name="Root", password="secret123")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_active)
        self.assertTrue(admin.is_verified)

    def test_default_role_is_a_valid_choice(self):
        """
        KNOWN BUG: User.role default is "Lead", but ROLE_CHOICES only allows
        "admin", "manager", "member". A freshly created user (without an
        explicit role) therefore has an out-of-spec role value.
        This test encodes the *correct* expectation and will fail until the
        model default is fixed to one of the declared choices.
        """
        user = User.objects.create_user(email="default-role@test.com", u_name="X", password="secret123")
        valid_values = [choice[0] for choice in User.ROLE_CHOICES]
        self.assertIn(user.role, valid_values)

    def test_soft_delete_sets_flag(self):
        user = User.objects.create_user(email="del@test.com", u_name="Del", password="secret123")
        self.assertFalse(user.is_deleted)
        user.soft_delete()
        user.refresh_from_db()
        self.assertTrue(user.is_deleted)

    def test_str_representation(self):
        user = User.objects.create_user(email="str@test.com", u_name="StrTest", password="secret123")
        self.assertIn("str@test.com", str(user))
        self.assertIn("StrTest", str(user))

    def test_accessing_primary_key_does_not_recurse(self):
        """
        KNOWN BUG: models.py defines both
            id = models.AutoField(primary_key=True)
        and, further down the class body,
            @property
            def id(self): return self.id
        The property shadows the field descriptor and recurses into itself
        forever. Any code path that reads `user.id` should return an int,
        not blow up with a RecursionError.
        """
        user = User.objects.create_user(email="pk@test.com", u_name="PK", password="secret123")
        try:
            pk_value = user.id
        except RecursionError:
            self.fail(
                "User.id is a self-referential @property that shadows the "
                "AutoField and causes infinite recursion. Remove the "
                "duplicate `id` property from pms_app/models.py."
            )
        self.assertIsInstance(pk_value, int)


class ProjectModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pm@test.com", u_name="PM", password="secret123")

    def test_default_status_and_priority(self):
        project = Project.objects.create(p_name="P1", created_by=self.user)
        self.assertEqual(project.status, "planning")
        self.assertEqual(project.priority, "medium")
        self.assertFalse(project.is_deleted)

    def test_soft_delete(self):
        project = Project.objects.create(p_name="P1", created_by=self.user)
        project.soft_delete()
        project.refresh_from_db()
        self.assertTrue(project.is_deleted)

    def test_str_representation(self):
        project = Project.objects.create(p_name="Nice Project", created_by=self.user)
        self.assertEqual(str(project), "Nice Project")


class TaskModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="tm@test.com", u_name="TM", password="secret123")
        self.project = Project.objects.create(p_name="P1", created_by=self.user)

    def test_default_status_is_todo(self):
        task = Task.objects.create(title="T1", p=self.project, created_by=self.user)
        self.assertEqual(task.status, "todo")
        self.assertFalse(task.is_deleted)

    def test_task_requires_project(self):
        """Task.p has on_delete=CASCADE and is a required FK (no null=True)."""
        from django.db import IntegrityError, transaction
        with self.assertRaises((IntegrityError, ValueError)):
            with transaction.atomic():
                Task.objects.create(title="Orphan task", created_by=self.user)

    def test_deleting_project_cascades_to_tasks(self):
        task = Task.objects.create(title="T1", p=self.project, created_by=self.user)
        self.project.delete()  # hard delete on purpose to test CASCADE
        self.assertFalse(Task.objects.filter(t_id=task.t_id).exists())

    def test_soft_delete_does_not_hard_delete(self):
        task = Task.objects.create(title="T1", p=self.project, created_by=self.user)
        task.soft_delete()
        self.assertTrue(Task.objects.filter(t_id=task.t_id).exists())
        task.refresh_from_db()
        self.assertTrue(task.is_deleted)


class CommentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="c@test.com", u_name="C", password="secret123")
        self.project = Project.objects.create(p_name="P1", created_by=self.user)
        self.task = Task.objects.create(title="T1", p=self.project, created_by=self.user)

    def test_default_priority_and_pin(self):
        comment = Comment.objects.create(t=self.task, u=self.user, desc="hello")
        self.assertEqual(comment.priority, "normal")
        self.assertFalse(comment.pin)

    def test_ordering_is_newest_first(self):
        c1 = Comment.objects.create(t=self.task, u=self.user, desc="first")
        c2 = Comment.objects.create(t=self.task, u=self.user, desc="second")
        comments = list(Comment.objects.filter(t=self.task))
        self.assertEqual(comments[0].c_id, c2.c_id)
        self.assertEqual(comments[1].c_id, c1.c_id)


class NotificationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="n@test.com", u_name="N", password="secret123")

    def test_default_is_unread(self):
        notif = Notification.objects.create(u=self.user, type="task_assigned", message="hi")
        self.assertFalse(notif.is_read)
        self.assertIsNone(notif.read_at)

    def test_mark_as_read_sets_timestamp(self):
        notif = Notification.objects.create(u=self.user, type="task_assigned", message="hi")
        notif.mark_as_read()
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertIsNotNone(notif.read_at)
        self.assertLessEqual(notif.read_at, timezone.now())

    def test_deleting_user_cascades_to_notifications(self):
        notif = Notification.objects.create(u=self.user, type="x", message="y")
        self.user.delete()
        self.assertFalse(Notification.objects.filter(n_id=notif.n_id).exists())


class PTeamModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pt@test.com", u_name="PT", password="secret123")
        self.project = Project.objects.create(p_name="P1", created_by=self.user)
        self.task = Task.objects.create(title="T1", p=self.project, created_by=self.user)
        self.member = TeamMember.objects.create(name="Member1", added_by=self.user)

    def test_create_link(self):
        entry = PTeam.objects.create(p=self.project, t=self.task, tm=self.member)
        self.assertEqual(entry.p_id, self.project.p_id)
        self.assertEqual(entry.t_id, self.task.t_id)
        self.assertEqual(entry.tm_id, self.member.id)

    def test_task_is_optional(self):
        entry = PTeam.objects.create(p=self.project, tm=self.member)
        self.assertIsNone(entry.t)

    def test_member_is_optional(self):
        entry = PTeam.objects.create(p=self.project, t=self.task)
        self.assertIsNone(entry.tm)

    def test_deleting_project_cascades(self):
        entry = PTeam.objects.create(p=self.project, t=self.task, tm=self.member)
        self.project.delete()
        self.assertFalse(PTeam.objects.filter(pt_id=entry.pt_id).exists())

    def test_deleting_team_member_sets_null(self):
        entry = PTeam.objects.create(p=self.project, t=self.task, tm=self.member)
        self.member.delete()
        entry.refresh_from_db()
        self.assertIsNone(entry.tm)
