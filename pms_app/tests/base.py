"""
Shared base classes / fixtures for the pms_app test suite.

Design notes
------------
- We use DRF's APITestCase (wraps Django's Transactionless TestCase + APIClient).
- Each test method runs inside its own DB transaction that is rolled back at the
  end (Django TestCase behaviour), so tests are isolated from each other.
- `force_authenticate` is used for the majority of tests because it exercises
  the *view/permission/business logic* directly without paying the cost of a
  real JWT round-trip on every single test. The real JWT issuance/validation
  path itself is covered explicitly in `test_auth.py`, so we are not losing
  coverage — we are just not paying for it thousands of times over.
- Tests are written against the behaviour the API *should* have (per the
  README / sane REST semantics), not against whatever the current
  implementation happens to do. Where the current implementation is wrong,
  the test will fail and is clearly labelled so it's obvious this is a real
  bug and not a broken test.
"""
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status

from pms_app.models import User, TeamMember, Project, Task, Comment, Notification, PTeam


class BaseAPITestCase(APITestCase):
    """Common fixtures reused across most test modules."""

    def setUp(self):
        # ---- Users -------------------------------------------------
        self.admin = User.objects.create_user(
            email="admin@example.com", u_name="Admin User",
            password="StrongPass123", role="admin",
        )
        self.manager = User.objects.create_user(
            email="manager@example.com", u_name="Manager User",
            password="StrongPass123", role="manager",
        )
        self.member_user = User.objects.create_user(
            email="member@example.com", u_name="Member User",
            password="StrongPass123", role="member",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", u_name="Other User",
            password="StrongPass123", role="member",
        )

        # ---- Team member profile ------------------------------------
        self.team_member = TeamMember.objects.create(
            name="Ali Raza", skills="Python,Django", role="Developer",
            added_by=self.manager, qualitifcation="BSCS", experience=3,
        )

        # ---- Project ---------------------------------------------------
        self.project = Project.objects.create(
            p_name="Website Revamp", desc="Redesign company website",
            priority="high", created_by=self.manager, status="active",
        )

        # ---- Task -------------------------------------------------------
        self.task = Task.objects.create(
            title="Design homepage", desc="New homepage layout",
            status="todo", assign_to=self.team_member,
            assign_by=self.manager, created_by=self.manager,
            p=self.project, priority="high",
        )

        self.client.force_authenticate(user=self.manager)

    # -------- convenience helpers ------------------------------------
    def as_user(self, user):
        """Switch the authenticated user for the current client."""
        self.client.force_authenticate(user=user)

    def assertSuccess(self, response, code=status.HTTP_200_OK):
        self.assertEqual(response.status_code, code, response.content)
        self.assertTrue(response.data.get("success"), response.data)
        return response.data.get("data")

    def assertApiError(self, response, code):
        self.assertEqual(response.status_code, code, response.content)
        self.assertFalse(response.data.get("success", False), response.data)
