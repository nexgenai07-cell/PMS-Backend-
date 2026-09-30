"""
Full END-TO-END integration flows, based on the clarified business rules
(as described directly by the product owner, superseding/refining the
earlier PDF-derived assumptions in test_pms_user_stories_spec.py):

  1. Registration only has 2 roles: supervisor, lead.
  2. "Team Member" is NOT a login/auth account — it's a plain profile
     record (this matches the current `TeamMember` model already).
  3. Lead = manages/handles a project. Supervisor = oversees projects.
  4. Team members are added by leads/supervisors with no auth at all
     (MVP) — just a name/profile, then tasks get assigned to them.
  5. To put a LEAD into a project's team (as a team member), a Supervisor
     must first create that Lead's profile on the "Leads" page so it
     exists as a TeamMember row too — because by default a Lead only
     exists in the `users` table, not the `TeamMember` table.
  6. Project creation:
       - Supervisor creates a project and picks members/supervisor(s). If no
         supervisor picked, the creator becomes supervisor by default.
       - Lead MUST pick at least one supervisor when creating a project.
       - A project can have MULTIPLE supervisors (confirmed against the
         actual "Create Project" UI, which offers a multi-select supervisor
         picker) — so `Project` needs a many-to-many relationship to `User`
         for this, not a single `supervisor` FK. Every test below therefore
         sends/reads `supervisors` as a LIST of user ids, not a single id.
  7. Tasks are created and assigned to members; comments happen on tasks.
  8. Removing a member from a project who has an assigned task must NOT
     silently delete/orphan the task — the API must signal that a
     decision is needed (reassign to someone else, or leave unassigned),
     and accept that decision explicitly.

STATUS: like the other spec file, most of this does not exist in the
backend yet — these are full multi-step END-TO-END journeys, not
single-endpoint checks, so a failure can come from any step in the chain.
Read each test top-to-bottom; the first failing `assert`/status check
tells you exactly which step of the flow is unimplemented.

Every assumed endpoint/contract that isn't nailed down by the product
description is called out explicitly in the test's docstring.
"""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from pms_app.models import User, TeamMember, Project, Task, Comment, PTeam, Notification


def make_user(role, email, name="Test User"):
    user = User(email=email, u_name=name, role=role)
    user.set_password("StrongPass123")
    user.save()
    return user


# ===========================================================================
# 1) Supervisor — full happy-path project lifecycle, start to finish
# ===========================================================================
class SupervisorFullLifecycleE2ETests(APITestCase):
    def test_register_login_create_project_add_member_assign_task_comment(self):
        # Step 1: register as supervisor
        register = self.client.post(reverse("auth_register"), {
            "u_name": "Momina", "email": "momina@e2e.com",
            "password": "StrongPass123", "role": "supervisor",
        })
        self.assertEqual(register.status_code, status.HTTP_201_CREATED, register.content)

        # Step 2: login (real JWT, not force_authenticate — this is an
        # integration test, we want the real auth path exercised too)
        login = self.client.post(reverse("auth_login"), {
            "email": "momina@e2e.com", "password": "StrongPass123",
        })
        self.assertEqual(login.status_code, status.HTTP_200_OK, login.content)
        access = login.data["data"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        # Step 3: create a project, no supervisor specified -> auto-assigned
        project = self.client.post(reverse("project_list_CR"), {"p_name": "Website Revamp"})
        self.assertEqual(project.status_code, status.HTTP_201_CREATED, project.content)
        supervisor_id = User.objects.get(email="momina@e2e.com").id
        self.assertIn(supervisor_id, project.data["data"]["supervisors"])
        p_id = project.data["data"]["p_id"]

        # Step 4: add a team member, no auth fields required (MVP)
        member = self.client.post(reverse("team_member_list_CR"), {"name": "Ali Raza"})
        self.assertEqual(member.status_code, status.HTTP_201_CREATED, member.content)
        member_id = member.data["data"]["id"]

        # Step 5: put that member on the project
        add_member = self.client.post(f"/api/projects/{p_id}/members", {"team_member": member_id})
        self.assertEqual(add_member.status_code, status.HTTP_201_CREATED, add_member.content)

        # Step 6: create + assign a task to that member
        task = self.client.post(reverse("Create Task View"), {
            "title": "Design homepage", "p": p_id, "assign_to": member_id,
        })
        self.assertEqual(task.status_code, status.HTTP_201_CREATED, task.content)
        t_id = task.data["data"]["t_id"]

        # Step 7: comment on the task
        comment = self.client.post(reverse("CommentListCreateView"), {
            "t": t_id, "desc": "Please use the new brand colours",
        })
        self.assertEqual(comment.status_code, status.HTTP_201_CREATED, comment.content)

        # Step 8: everything should now be readable back through the API
        project_detail = self.client.get(reverse("project_details_view_UD", kwargs={"p_id": p_id}))
        self.assertEqual(project_detail.status_code, status.HTTP_200_OK)
        task_detail = self.client.get(reverse("TaskDetailView", kwargs={"t_id": t_id}))
        self.assertEqual(task_detail.data["data"]["assign_to"], member_id)
        comments = self.client.get(reverse("TaskCommentsView", kwargs={"t_id": t_id}))
        self.assertEqual(len(comments.data["data"]), 1)


# ===========================================================================
# 2) Lead — mandatory supervisor selection, end to end
# ===========================================================================
class LeadFullLifecycleE2ETests(APITestCase):
    def test_lead_blocked_without_supervisor_then_succeeds_with_one(self):
        lead = make_user("lead", "hamza-lead@e2e.com", "Hamza")
        supervisor = make_user("supervisor", "hamna@e2e.com", "Hamna")
        self.client.force_authenticate(user=lead)

        # Attempt without a supervisor -> must be rejected, nothing created
        blocked = self.client.post(reverse("project_list_CR"), {"p_name": "Mobile App"})
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST, blocked.content)
        self.assertFalse(Project.objects.filter(p_name="Mobile App").exists())

        # Now with a supervisor selected -> succeeds, and the Lead is NOT
        # the supervisor of record (they're just the creator)
        ok = self.client.post(reverse("project_list_CR"), {
            "p_name": "Mobile App", "supervisors": [supervisor.id],
        })
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED, ok.content)
        self.assertEqual(ok.data["data"]["supervisors"], [supervisor.id])
        self.assertEqual(ok.data["data"]["created_by"], lead.id)
        self.assertNotIn(lead.id, ok.data["data"]["supervisors"])

        # The rest of the flow (members/tasks/comments) works the same way
        # as the supervisor flow above.
        p_id = ok.data["data"]["p_id"]
        member = self.client.post(reverse("team_member_list_CR"), {"name": "Team Member X"})
        member_id = member.data["data"]["id"]
        self.client.post(f"/api/projects/{p_id}/members", {"team_member": member_id})
        task = self.client.post(reverse("Create Task View"), {
            "title": "Build login screen", "p": p_id, "assign_to": member_id,
        })
        self.assertEqual(task.status_code, status.HTTP_201_CREATED, task.content)

    def test_a_project_can_have_multiple_supervisors_at_once(self):
        """The actual "Create Project" UI offers a multi-select supervisor
        picker (confirmed via screenshot) — a project must be able to carry
        more than one supervisor, not just one."""
        lead = make_user("lead", "multi-lead@e2e.com", "Multi Lead")
        sup_1 = make_user("supervisor", "sup1@e2e.com", "Sup One")
        sup_2 = make_user("supervisor", "sup2@e2e.com", "Sup Two")
        self.client.force_authenticate(user=lead)

        response = self.client.post(reverse("project_list_CR"), {
            "p_name": "Multi-Supervisor Project", "supervisors": [sup_1.id, sup_2.id],
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertCountEqual(response.data["data"]["supervisors"], [sup_1.id, sup_2.id])

        # both supervisors should be able to see/open the project
        for sup in (sup_1, sup_2):
            self.client.force_authenticate(user=sup)
            listing = self.client.get(reverse("project_list_CR"))
            names = [p["p_name"] for p in listing.data["data"]]
            self.assertIn("Multi-Supervisor Project", names)


# ===========================================================================
# 3) Project visibility — THE critical integration check
# ===========================================================================
class ProjectVisibilityIntegrationTests(APITestCase):
    """
    Right now `ProjectListCreateView` returns every project to every
    authenticated user, with no filtering by role/ownership/membership at
    all. This is the single most important gap to close: a Lead must only
    ever see projects they created or were explicitly added to.
    """

    def setUp(self):
        self.supervisor_a = make_user("supervisor", "supA@vis.com", "Supervisor A")
        self.lead_owner = make_user("lead", "leadOwner@vis.com", "Lead Owner")
        self.lead_outsider = make_user("lead", "leadOutsider@vis.com", "Lead Outsider")

        self.client.force_authenticate(user=self.lead_owner)
        create = self.client.post(reverse("project_list_CR"), {
            "p_name": "Owner's Project", "supervisors": [self.supervisor_a.id],
        })
        self.p_id = create.data["data"]["p_id"]

    def test_outsider_lead_does_not_see_project_in_list(self):
        self.client.force_authenticate(user=self.lead_outsider)
        listing = self.client.get(reverse("project_list_CR"))
        names = [p["p_name"] for p in listing.data["data"]]
        self.assertNotIn("Owner's Project", names)

    def test_outsider_lead_cannot_open_project_detail_directly(self):
        """BR-16 equivalent: guessing/incrementing the p_id in the URL must
        not work even though the project exists."""
        self.client.force_authenticate(user=self.lead_outsider)
        detail = self.client.get(reverse("project_details_view_UD", kwargs={"p_id": self.p_id}))
        self.assertIn(detail.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_outsider_lead_cannot_see_its_tasks_either(self):
        Task.objects.create(title="Owner's task", p_id=self.p_id, created_by=self.lead_owner)
        self.client.force_authenticate(user=self.lead_outsider)
        tasks = self.client.get(reverse("ProjectTasksView", kwargs={"p_id": self.p_id}))
        self.assertIn(tasks.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_owner_lead_still_sees_their_own_project(self):
        self.client.force_authenticate(user=self.lead_owner)
        listing = self.client.get(reverse("project_list_CR"))
        names = [p["p_name"] for p in listing.data["data"]]
        self.assertIn("Owner's Project", names)

    def test_supervisor_on_the_project_sees_it_too(self):
        self.client.force_authenticate(user=self.supervisor_a)
        listing = self.client.get(reverse("project_list_CR"))
        names = [p["p_name"] for p in listing.data["data"]]
        self.assertIn("Owner's Project", names)

    def test_once_added_the_outsider_lead_can_see_it(self):
        self.client.force_authenticate(user=self.lead_owner)
        add = self.client.post(f"/api/projects/{self.p_id}/members", {"user": self.lead_outsider.id})
        self.assertEqual(add.status_code, status.HTTP_201_CREATED, add.content)

        self.client.force_authenticate(user=self.lead_outsider)
        listing = self.client.get(reverse("project_list_CR"))
        names = [p["p_name"] for p in listing.data["data"]]
        self.assertIn("Owner's Project", names)


# ===========================================================================
# 4) Lead -> Team Member conversion ("Leads page" on the Supervisor side)
# ===========================================================================
class LeadToTeamMemberConversionE2ETests(APITestCase):
    """
    A Lead only exists in the `users` table by default. To assign a Lead
    tasks the same way a regular team member gets tasks, a Supervisor must
    create a TeamMember profile *linked back* to that Lead's user account
    via the "Leads" page.

    ASSUMED CONTRACT (not specified exactly by the product owner):
      POST /api/team_members/from-lead   { "user": <lead_user_id> }
      -> 201, creates a TeamMember row whose `name` is copied from the
         Lead's `u_name`, and which carries a `linked_user` field pointing
         back at that User (this field does not exist on `TeamMember` yet
         and needs to be added).
    """

    def test_supervisor_converts_a_lead_into_an_assignable_team_member(self):
        supervisor_a = make_user("supervisor", "supA@conv.com", "Supervisor A")
        lead_x = make_user("lead", "leadX@conv.com", "Lead X")

        self.client.force_authenticate(user=supervisor_a)
        convert = self.client.post("/api/team_members/from-lead", {"user": lead_x.id})
        self.assertEqual(convert.status_code, status.HTTP_201_CREATED, convert.content)
        self.assertEqual(convert.data["data"]["name"], "Lead X")

        member_id = convert.data["data"]["id"]
        member = TeamMember.objects.get(id=member_id)
        self.assertEqual(getattr(member, "linked_user_id", None), lead_x.id)

    def test_converted_lead_can_then_be_added_to_a_project_and_assigned_tasks(self):
        supervisor_a = make_user("supervisor", "supA@conv2.com", "Supervisor A")
        lead_x = make_user("lead", "leadX2@conv2.com", "Lead X")
        self.client.force_authenticate(user=supervisor_a)

        convert = self.client.post("/api/team_members/from-lead", {"user": lead_x.id})
        member_id = convert.data["data"]["id"]

        project = self.client.post(reverse("project_list_CR"), {"p_name": "Cross-functional Project"})
        p_id = project.data["data"]["p_id"]
        self.client.post(f"/api/projects/{p_id}/members", {"team_member": member_id})

        task = self.client.post(reverse("Create Task View"), {
            "title": "Review architecture", "p": p_id, "assign_to": member_id,
        })
        self.assertEqual(task.status_code, status.HTTP_201_CREATED, task.content)

    def test_duplicate_conversion_of_the_same_lead_is_rejected(self):
        supervisor_a = make_user("supervisor", "supA@conv3.com", "Supervisor A")
        lead_x = make_user("lead", "leadX3@conv3.com", "Lead X")
        self.client.force_authenticate(user=supervisor_a)

        first = self.client.post("/api/team_members/from-lead", {"user": lead_x.id})
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.client.post("/api/team_members/from-lead", {"user": lead_x.id})
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)


# ===========================================================================
# 5) Removing a member from a project who has an assigned task
# ===========================================================================
class MemberRemovalReassignmentE2ETests(APITestCase):
    """
    ASSUMED CONTRACT:
      DELETE /api/pteam/<pt_id>
        -> if the member has task(s) assigned on this project and no
           decision was supplied, respond 409 CONFLICT with the list of
           affected task ids, instead of silently deleting the link.
      DELETE /api/pteam/<pt_id>?reassign_to=<other_team_member_id>
        -> reassigns the affected task(s) to the other member, then
           removes the membership link. 200.
      DELETE /api/pteam/<pt_id>?unassign=true
        -> clears `assign_to` on the affected task(s) (task stays,
           unassigned), then removes the membership link. 200.
    """

    def setUp(self):
        self.supervisor_a = make_user("supervisor", "supA@rem.com", "Supervisor A")
        self.project = Project.objects.create(p_name="Removal Project", created_by=self.supervisor_a)
        self.member_a = TeamMember.objects.create(name="Member A", added_by=self.supervisor_a)
        self.member_b = TeamMember.objects.create(name="Member B", added_by=self.supervisor_a)
        self.link = PTeam.objects.create(p=self.project, tm=self.member_a)
        self.task = Task.objects.create(title="Assigned task", p=self.project,
                                         created_by=self.supervisor_a, assign_to=self.member_a)
        self.client.force_authenticate(user=self.supervisor_a)

    def test_removal_with_no_decision_asks_for_one_instead_of_silently_deleting(self):
        url = reverse("pteam-detail", kwargs={"pt_id": self.link.pt_id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.content)
        # the membership link and the task assignment must both be untouched
        self.assertTrue(PTeam.objects.filter(pt_id=self.link.pt_id).exists())
        self.task.refresh_from_db()
        self.assertEqual(self.task.assign_to_id, self.member_a.id)

    def test_removal_with_explicit_reassignment(self):
        url = reverse("pteam-detail", kwargs={"pt_id": self.link.pt_id})
        response = self.client.delete(url, {"reassign_to": self.member_b.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertFalse(PTeam.objects.filter(pt_id=self.link.pt_id).exists())
        self.task.refresh_from_db()
        self.assertEqual(self.task.assign_to_id, self.member_b.id)

    def test_removal_with_explicit_unassign(self):
        url = reverse("pteam-detail", kwargs={"pt_id": self.link.pt_id})
        response = self.client.delete(url, {"unassign": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.assign_to)
        # the task itself must still exist, just unassigned
        self.assertTrue(Task.objects.filter(t_id=self.task.t_id).exists())

    def test_removal_of_member_with_no_assigned_tasks_needs_no_decision(self):
        free_link = PTeam.objects.create(p=self.project, tm=self.member_b)
        url = reverse("pteam-detail", kwargs={"pt_id": free_link.pt_id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


# ===========================================================================
# 6) Team members require no auth at all (MVP) — sanity check
# ===========================================================================
class TeamMemberNoAuthMVPTests(APITestCase):
    """This one should already pass with the current model — TeamMember
    has no email/password/login fields at all — but it's worth pinning
    down explicitly as a regression guard, since it's an intentional MVP
    design decision the product owner called out and it would be easy for
    a future change to accidentally start requiring auth fields here."""

    def test_team_member_creation_needs_only_a_name(self):
        supervisor_a = make_user("supervisor", "supA@noauth.com", "Supervisor A")
        self.client.force_authenticate(user=supervisor_a)
        response = self.client.post(reverse("team_member_list_CR"), {"name": "Just A Name"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertNotIn("password", response.data["data"])
        self.assertNotIn("email", response.data["data"])

    def test_team_member_model_has_no_password_field(self):
        self.assertFalse(hasattr(TeamMember, "password"))
        self.assertFalse(hasattr(TeamMember, "check_password"))


# ===========================================================================
# 7) Cross-project security — chained integration attack attempt
# ===========================================================================
class CrossProjectSecurityE2ETests(APITestCase):
    """One continuous "attack" flow: an outsider Lead tries every avenue
    (list, direct id, task creation, assignment, commenting) against a
    project they have no relationship to, and every single one must be
    blocked — a single gap anywhere in this chain is a real vulnerability."""

    def test_full_unauthorized_access_attempt_is_blocked_at_every_step(self):
        supervisor_a = make_user("supervisor", "supA@sec.com", "Supervisor A")
        owner_lead = make_user("lead", "owner@sec.com", "Owner Lead")
        attacker_lead = make_user("lead", "attacker@sec.com", "Attacker Lead")

        self.client.force_authenticate(user=owner_lead)
        project = self.client.post(reverse("project_list_CR"), {
            "p_name": "Confidential Project", "supervisors": [supervisor_a.id],
        })
        p_id = project.data["data"]["p_id"]
        member = self.client.post(reverse("team_member_list_CR"), {"name": "Confidential Member"})
        member_id = member.data["data"]["id"]
        self.client.post(f"/api/projects/{p_id}/members", {"team_member": member_id})
        task = self.client.post(reverse("Create Task View"), {
            "title": "Confidential task", "p": p_id, "assign_to": member_id,
        })
        t_id = task.data["data"]["t_id"]

        # --- now switch to the attacker ---
        self.client.force_authenticate(user=attacker_lead)

        listing = self.client.get(reverse("project_list_CR"))
        self.assertNotIn(p_id, [p["p_id"] for p in listing.data["data"]])

        detail = self.client.get(reverse("project_details_view_UD", kwargs={"p_id": p_id}))
        self.assertIn(detail.status_code, (403, 404))

        tasks_view = self.client.get(reverse("ProjectTasksView", kwargs={"p_id": p_id}))
        self.assertIn(tasks_view.status_code, (403, 404))

        task_detail = self.client.get(reverse("TaskDetailView", kwargs={"t_id": t_id}))
        self.assertIn(task_detail.status_code, (403, 404))

        sneaky_task = self.client.post(reverse("Create Task View"), {
            "title": "Injected task", "p": p_id,
        })
        self.assertIn(sneaky_task.status_code, (400, 403))

        sneaky_comment = self.client.post(reverse("CommentListCreateView"), {
            "t": t_id, "desc": "I shouldn't be here",
        })
        self.assertEqual(sneaky_comment.status_code, 403)

        sneaky_member_add = self.client.post(f"/api/projects/{p_id}/members", {
            "team_member": member_id,
        })
        self.assertIn(sneaky_member_add.status_code, (400, 403, 404))