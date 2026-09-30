from django.utils import timezone
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.mail import send_mail
from django.conf import settings
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from .tokens import email_verification_token
from .serializers import VerifyEmailSerializer, ResendVerificationSerializer

from .models import User, TeamMember, Project, Task, Comment, Notification, PTeam
from .serializers import (
    RegisterSerializer, LoginSerializer, UserSerializer,TeamMemberSerializer, ProjectSerializer, ProjectListSerializer,TaskSerializer,TaskListSerializer, CommentSerializer, NotificationSerializer, PTeamSerializer, ProjectStatsSerializer
)



# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def success(data, status_code=status.HTTP_200_OK):
    return Response({"success": True, "data": data}, status=status_code)

def error(msg, status_code=status.HTTP_400_BAD_REQUEST):
    return Response({"success": False, "error": msg}, status=status_code)

# ─────────────────────────────────────────────
# Email verification helpers
# ─────────────────────────────────────────────

def _build_verification_link(request, user):
    """Build the frontend verification URL with uid + token."""
    uid   = urlsafe_base64_encode(force_bytes(user.id))
    token = email_verification_token.make_token(user)
    base  = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    return f"{base}/verify-email?uid={uid}&token={token}"


def _send_verification_email(user, verification_link):
    """Send the verification email using Django's configured backend."""
    subject = "Verify your AEEL-PMS account"
    message = (
        f"Hi {user.u_name},\n\n"
        f"Thanks for registering with AEEL-PMS.\n\n"
        f"Please click the link below to verify your email address. "
        f"This link expires in 24 hours.\n\n"
        f"{verification_link}\n\n"
        f"If you didn't create this account, you can safely ignore this email.\n\n"
        f"— The AEEL-PMS Team"
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

# ═══════════════════════════════════════════════════════════════
# AUTH VIEWS
# ═══════════════════════════════════════════════════════════════

class RegisterView(APIView):
    """POST /api/auth/register/"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return error(serializer.errors)

        user = serializer.save()

        # Build link + send email. If email fails, delete the user so they
        # can retry with the same email.
        try:
            link = _build_verification_link(request, user)
            _send_verification_email(user, link)
        except Exception as e:
            user.delete()
            return error(
                {"detail": f"Could not send verification email: {e}. Please try again."},
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return success(
            {
                "message": "User registered. Please check your email to verify.",
                "user_id": user.id,
                "email":   user.email,
            },
            status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """POST /api/auth/login/"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            return success(serializer.validated_data)

        # Inspect error code so we can return 403 for email-not-verified
        errors = serializer.errors
        non_field = errors.get('non_field_errors')

        code = None
        detail = None
        if isinstance(non_field, dict):
            code   = non_field.get('code')
            detail = non_field.get('detail')
        elif isinstance(non_field, list) and non_field:
            detail = non_field[0]

        if code == 'EMAIL_NOT_VERIFIED':
            return Response(
                {
                    "success": False,
                    "error":   {"detail": detail, "code": code},
                    "detail":  detail,
                    "code":    code,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if code in ('INVALID_PASSWORD', 'NO_ACCOUNT', 'ACCOUNT_INACTIVE',
                    'ACCOUNT_DELETED'):
            return Response(
                {
                    "success": False,
                    "error":   {"detail": detail, "code": code},
                    "detail":  detail,
                    "code":    code,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return error(serializer.errors, status.HTTP_401_UNAUTHORIZED)


class LogoutView(APIView):
    """POST /api/auth/logout/  — blacklists the refresh token"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get("refresh"))
            token.blacklist()
            return success({"message": "Logged out successfully."})
        except Exception as e:
            return error(str(e))

class VerifyEmailView(APIView):
    """POST /api/auth/verify-email/  — body: { uid, token }"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        if not serializer.is_valid():
            return error(serializer.errors, status.HTTP_400_BAD_REQUEST)

        user = serializer.context["user"]

        if user.is_verified and user.is_active:
            return success({
                "message": "Email already verified. You can log in.",
                "already_verified": True,
            })

        user.is_verified = True
        user.is_active   = True
        user.save(update_fields=['is_verified', 'is_active'])

        return success({
            "message": "Email verified successfully. You can now log in.",
            "email":   user.email,
        })


class ResendVerificationView(APIView):
    """POST /api/auth/resend-verification/  — body: { email }"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        if not serializer.is_valid():
            return error(serializer.errors, status.HTTP_400_BAD_REQUEST)

        user = serializer.context.get("user")

        # Always return success to prevent email enumeration.
        # Only actually send if the user exists AND isn't verified.
        if user and not user.is_verified and not user.is_deleted:
            try:
                link = _build_verification_link(request, user)
                _send_verification_email(user, link)
            except Exception:
                pass  # swallow — don't leak whether the send worked

        return success({
            "message": (
                "If an account exists with that email and is unverified, "
                "a new link has been sent."
            )
        })
        
class MeView(APIView):
    """GET /api/auth/me/  — current user profile"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return success(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success(serializer.data)
        return error(serializer.errors)


# ═══════════════════════════════════════════════════════════════
# USER VIEWS
# ═══════════════════════════════════════════════════════════════

class UserListView(APIView):
    """GET /api/users/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        users = User.objects.filter(is_deleted=False)
        return success(UserSerializer(users, many=True).data)


class UserDetailView(APIView):
    """GET / PATCH / DELETE /api/users/<u_id>/"""
    permission_classes = [IsAuthenticated]

    def _get_user(self, id):
        try:
            return User.objects.get(id=id, is_deleted=False)
        except User.DoesNotExist:
            return None

    def get(self, request, id):
        user = self._get_user(id)
        if not user:
            return error("User not found.", status.HTTP_404_NOT_FOUND)
        return success(UserSerializer(user).data)

    def patch(self, request, id):
        user = self._get_user(id)
        if not user:
            return error("User not found.", status.HTTP_404_NOT_FOUND)
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success(serializer.data)
        return error(serializer.errors)

    def delete(self, request, id):
        user = self._get_user(id)
        if not user:
            return error("User not found.", status.HTTP_404_NOT_FOUND)
        user.soft_delete()
        return success({"message": "User deleted."})

# ═══════════════════════════════════════════════════════════════
# TEAM MEMBER VIEWS
# ═══════════════════════════════════════════════════════════════

class TeamMemberListCreateView(APIView):
    """GET /api/team-members/   POST /api/team-members/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        members = TeamMember.objects.filter(is_deleted=0).order_by("name")
        return success(TeamMemberSerializer(members, many=True).data)

    def post(self, request):
        serializer = TeamMemberSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            member = serializer.save()
            return success(TeamMemberSerializer(member).data, status.HTTP_201_CREATED)
        return error(serializer.errors)


class TeamMemberDetailView(APIView):
    """GET / PATCH / DELETE /api/team-members/<id>/"""
    permission_classes = [IsAuthenticated]

    def _get_member(self, id):
        try:
            return TeamMember.objects.get(id=id, is_deleted=0)
        except TeamMember.DoesNotExist:
            return None

    def get(self, request, id):
        member = self._get_member(id)
        if not member:
            return error("Team member not found.", status.HTTP_404_NOT_FOUND)
        return success(TeamMemberSerializer(member).data)

    def patch(self, request, id):
        member = self._get_member(id)
        if not member:
            return error("Team member not found.", status.HTTP_404_NOT_FOUND)
        serializer = TeamMemberSerializer(member, data=request.data, partial=True,
                                          context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return success(serializer.data)
        return error(serializer.errors)

    def delete(self, request, id):
        member = self._get_member(id)
        if not member:
            return error("Team member not found.", status.HTTP_404_NOT_FOUND)
        member.is_deleted = 1
        member.save()
        return success({"message": "Team member deleted."})

# ═══════════════════════════════════════════════════════════════
# PROJECT VIEWS
# ═══════════════════════════════════════════════════════════════

class ProjectListCreateView(APIView):
    """GET /api/projects/   POST /api/projects/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        projects = Project.objects.filter(is_deleted=False).order_by("-created_at")
        return success(ProjectListSerializer(projects, many=True).data)

    def post(self, request):
        serializer = ProjectSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            project = serializer.save()
            return success(ProjectSerializer(project).data, status.HTTP_201_CREATED)
        return error(serializer.errors)


class ProjectDetailView(APIView):
    """GET / PATCH / DELETE /api/projects/<p_id>/"""
    permission_classes = [IsAuthenticated]

    def _get_project(self, p_id):
        try:
            return Project.objects.get(p_id=p_id, is_deleted=False)
        except Project.DoesNotExist:
            return None

    def get(self, request, p_id):
        project = self._get_project(p_id)
        if not project:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)
        return success(ProjectSerializer(project).data)

    def patch(self, request, p_id):
        project = self._get_project(p_id)
        if not project:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)
        serializer = ProjectSerializer(project, data=request.data, partial=True,
                                       context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return success(serializer.data)
        return error(serializer.errors)

    def delete(self, request, p_id):
        project = self._get_project(p_id)
        if not project:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)
        project.soft_delete()
        return success({"message": "Project deleted."})


class ProjectTasksView(APIView):
    """GET /api/projects/<p_id>/tasks/  — all tasks under a project"""
    permission_classes = [IsAuthenticated]

    def get(self, request, p_id):
        tasks = Task.objects.filter(p__p_id=p_id, is_deleted=False).order_by("-created_at")
        return success(TaskListSerializer(tasks, many=True).data)


class ProjectStatsView(APIView):
    """GET /api/projects/<p_id>/stats/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, p_id):
        # get project
        try:
            project = Project.objects.get(p_id=p_id, is_deleted=False)
        except Project.DoesNotExist:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)

        # get all tasks for this project
        tasks = Task.objects.filter(p__p_id=p_id, is_deleted=False)

        total_tasks       = tasks.count()
        completed_tasks   = tasks.filter(status="done").count()
        in_progress_tasks = tasks.filter(status="in_progress").count()
        todo_tasks        = tasks.filter(status="todo").count()

        # completion rate
        completion_rate = (
            round((completed_tasks / total_tasks) * 100, 1)
            if total_tasks > 0 else 0
        )

        # on time rate — tasks completed before due date
        now = timezone.now()
        tasks_with_due = tasks.filter(due_date__isnull=False)
        on_time_tasks  = tasks_with_due.filter(
            status="done",
            due_date__gte=now
        ).count()
        on_time_rate = (
            round((on_time_tasks / tasks_with_due.count()) * 100, 1)
            if tasks_with_due.count() > 0 else 0
        )

        # members count via PTeam
        members_count = PTeam.objects.filter(
            p__p_id=p_id
        ).values("tm").distinct().count()

        # avg progress — weight each status
        STATUS_WEIGHT = {
            "todo":        0,
            "in_progress": 50,
            "review":      75,
            "done":        100,
            "cancelled":   0,
        }
        avg_progress = 0
        if total_tasks > 0:
            total_weight = sum(
                STATUS_WEIGHT.get(t.status, 0)
                for t in tasks
            )
            avg_progress = round(total_weight / total_tasks, 1)

        data = {
            "totalTasks":      total_tasks,
            "completedTasks":  completed_tasks,
            "inProgressTasks": in_progress_tasks,
            "todoTasks":       todo_tasks,
            "completionRate":  completion_rate,
            "onTimeRate":      on_time_rate,
            "membersCount":    members_count,
            "avgProgress":     avg_progress,
        }

        serializer = ProjectStatsSerializer(data)
        return success(serializer.data)

# ═══════════════════════════════════════════════════════════════
# TASK VIEWS
# ═══════════════════════════════════════════════════════════════

class TaskListCreateView(APIView):
    """GET /api/tasks/   POST /api/tasks/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tasks = Task.objects.filter(is_deleted=False).order_by("-created_at")
        # Optional filters via query params
        status_filter   = request.query_params.get("status")
        priority_filter = request.query_params.get("priority")
        assigned_to     = request.query_params.get("assign_to")
        project_id      = request.query_params.get("project")

        if status_filter:
            tasks = tasks.filter(status=status_filter)
        if priority_filter:
            tasks = tasks.filter(priority=priority_filter)
        if assigned_to:
            tasks = tasks.filter(assign_to__u_id=assigned_to)
        if project_id:
            tasks = tasks.filter(p__p_id=project_id)

        return success(TaskListSerializer(tasks, many=True).data)

    def post(self, request):
        serializer = TaskSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            task = serializer.save()
            return success(TaskSerializer(task).data, status.HTTP_201_CREATED)
        return error(serializer.errors)


class TaskDetailView(APIView):
    """GET / PATCH / DELETE /api/tasks/<t_id>/"""
    permission_classes = [IsAuthenticated]

    def _get_task(self, t_id):
        try:
            return Task.objects.get(t_id=t_id, is_deleted=False)
        except Task.DoesNotExist:
            return None

    def get(self, request, t_id):
        task = self._get_task(t_id)
        if not task:
            return error("Task not found.", status.HTTP_404_NOT_FOUND)
        return success(TaskSerializer(task).data)

    def patch(self, request, t_id):
        task = self._get_task(t_id)
        if not task:
            return error("Task not found.", status.HTTP_404_NOT_FOUND)
        serializer = TaskSerializer(task, data=request.data, partial=True,
                                    context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return success(serializer.data)
        return error(serializer.errors)

    def delete(self, request, t_id):
        task = self._get_task(t_id)
        if not task:
            return error("Task not found.", status.HTTP_404_NOT_FOUND)
        task.soft_delete()
        return success({"message": "Task deleted."})


class TaskCommentsView(APIView):
    """GET /api/tasks/<t_id>/comments/  — all comments on a task"""
    permission_classes = [IsAuthenticated]

    def get(self, request, t_id):
        comments = Comment.objects.filter(t__t_id=t_id).order_by("-created_at")
        return success(CommentSerializer(comments, many=True).data)

# ═══════════════════════════════════════════════════════════════
# COMMENT VIEWS
# ═══════════════════════════════════════════════════════════════

class CommentListCreateView(APIView):
    """GET /api/comments/   POST /api/comments/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        comments = Comment.objects.all().order_by("-created_at")
        return success(CommentSerializer(comments, many=True).data)

    def post(self, request):
        serializer = CommentSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            comment = serializer.save()
            return success(CommentSerializer(comment).data, status.HTTP_201_CREATED)
        return error(serializer.errors)


class CommentDetailView(APIView):
    """GET / PATCH / DELETE /api/comments/<c_id>/"""
    permission_classes = [IsAuthenticated]

    def _get_comment(self, c_id):
        try:
            return Comment.objects.get(c_id=c_id)
        except Comment.DoesNotExist:
            return None

    def get(self, request, c_id):
        comment = self._get_comment(c_id)
        if not comment:
            return error("Comment not found.", status.HTTP_404_NOT_FOUND)
        return success(CommentSerializer(comment).data)

    def patch(self, request, c_id):
        comment = self._get_comment(c_id)
        if not comment:
            return error("Comment not found.", status.HTTP_404_NOT_FOUND)
        if comment.u != request.user:
            return error("You can only edit your own comments.", status.HTTP_403_FORBIDDEN)
        serializer = CommentSerializer(comment, data=request.data, partial=True,
                                       context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return success(serializer.data)
        return error(serializer.errors)

    def delete(self, request, c_id):
        comment = self._get_comment(c_id)
        if not comment:
            return error("Comment not found.", status.HTTP_404_NOT_FOUND)
        if comment.u != request.user:
            return error("You can only delete your own comments.", status.HTTP_403_FORBIDDEN)
        comment.delete()
        return success({"message": "Comment deleted."})


class CommentPinView(APIView):
    """PATCH /api/comments/<c_id>/pin/  — toggle pin"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, c_id):
        try:
            comment = Comment.objects.get(c_id=c_id)
        except Comment.DoesNotExist:
            return error("Comment not found.", status.HTTP_404_NOT_FOUND)
        comment.pin = not comment.pin
        comment.save()
        return success({"pinned": comment.pin})


# ═══════════════════════════════════════════════════════════════
# NOTIFICATION VIEWS
# ═══════════════════════════════════════════════════════════════

class NotificationListView(APIView):
    """GET /api/notifications/  — current user's notifications"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(
            u=request.user, is_deleted__isnull=True
        ).order_by("-created_at")
        return success(NotificationSerializer(notifications, many=True).data)


class NotificationDetailView(APIView):
    """GET /api/notifications/<n_id>/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, n_id):
        try:
            notification = Notification.objects.get(n_id=n_id, u=request.user)
        except Notification.DoesNotExist:
            return error("Notification not found.", status.HTTP_404_NOT_FOUND)
        return success(NotificationSerializer(notification).data)


class NotificationMarkReadView(APIView):
    """PATCH /api/notifications/<n_id>/read/"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, n_id):
        try:
            notification = Notification.objects.get(n_id=n_id, u=request.user)
        except Notification.DoesNotExist:
            return error("Notification not found.", status.HTTP_404_NOT_FOUND)
        notification.mark_as_read()
        return success({"message": "Notification marked as read."})


class NotificationMarkAllReadView(APIView):
    """PATCH /api/notifications/read-all/"""
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        now = timezone.now()
        Notification.objects.filter(
            u=request.user, is_read=False
        ).update(is_read=True, read_at=now)
        return success({"message": "All notifications marked as read."})


class NotificationDeleteView(APIView):
    """DELETE /api/notifications/<n_id>/"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, n_id):
        try:
            notification = Notification.objects.get(n_id=n_id, u=request.user)
        except Notification.DoesNotExist:
            return error("Notification not found.", status.HTTP_404_NOT_FOUND)
        notification.is_deleted = timezone.now()
        notification.save()
        return success({"message": "Notification deleted."})

# ═══════════════════════════════════════════════════════════════
# P_TEAM VIEWS
# ═══════════════════════════════════════════════════════════════

class PTeamListCreateView(APIView):
    """GET /api/pteam/   POST /api/pteam/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        entries = PTeam.objects.select_related("p", "t", "tm").all()
        project_id = request.query_params.get("project")
        if project_id:
            entries = entries.filter(p__p_id=project_id)
        return success(PTeamSerializer(entries, many=True).data)

    def post(self, request):
        serializer = PTeamSerializer(data=request.data)
        if serializer.is_valid():
            entry = serializer.save()
            return success(PTeamSerializer(entry).data, status.HTTP_201_CREATED)
        return error(serializer.errors)


class PTeamDetailView(APIView):
    """GET / DELETE /api/pteam/<pt_id>/"""
    permission_classes = [IsAuthenticated]

    def _get_entry(self, pt_id):
        try:
            return PTeam.objects.get(pt_id=pt_id)
        except PTeam.DoesNotExist:
            return None

    def get(self, request, pt_id):
        entry = self._get_entry(pt_id)
        if not entry:
            return error("PTeam entry not found.", status.HTTP_404_NOT_FOUND)
        return success(PTeamSerializer(entry).data)

    def delete(self, request, pt_id):
        entry = self._get_entry(pt_id)
        if not entry:
            return error("PTeam entry not found.", status.HTTP_404_NOT_FOUND)
        entry.delete()
        return success({"message": "PTeam entry removed."})


# ═══════════════════════════════════════════════════════════════
# MEMBER STATS  GET /api/team-members/<id>/stats/
# ═══════════════════════════════════════════════════════════════

class TeamMemberStatsView(APIView):
    """GET /api/team-members/<id>/stats/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        try:
            member = TeamMember.objects.get(id=id, is_deleted=0)
        except TeamMember.DoesNotExist:
            return error("Team member not found.", status.HTTP_404_NOT_FOUND)

        # ✅ fixed — filter by tm (TeamMember FK), not pt_id
        pteam_entries = PTeam.objects.filter(tm__id=id)

        # task IDs assigned to this member
        task_ids = pteam_entries.values_list("t__t_id", flat=True)
        tasks    = Task.objects.filter(t_id__in=task_ids, is_deleted=False)

        total_tasks       = tasks.count()
        completed_tasks   = tasks.filter(status="done").count()
        in_progress_tasks = tasks.filter(status="in_progress").count()
        todo_tasks        = tasks.filter(status="todo").count()
        review_tasks      = tasks.filter(status="review").count()
        cancelled_tasks   = tasks.filter(status="cancelled").count()

        # completion rate
        completion_rate = (
            round((completed_tasks / total_tasks) * 100, 1)
            if total_tasks > 0 else 0
        )

        # on time rate
        now            = timezone.now()
        tasks_with_due = tasks.filter(due_date__isnull=False)
        on_time_tasks  = tasks_with_due.filter(
            status="done", due_date__gte=now
        ).count()
        on_time_rate = (
            round((on_time_tasks / tasks_with_due.count()) * 100, 1)
            if tasks_with_due.count() > 0 else 0
        )

        # projects this member is part of
        projects_count = pteam_entries.values("p").distinct().count()

        # avg progress
        STATUS_WEIGHT = {
            "todo": 0, "in_progress": 50,
            "review": 75, "done": 100, "cancelled": 0,
        }
        avg_progress = 0
        if total_tasks > 0:
            total_weight = sum(STATUS_WEIGHT.get(t.status, 0) for t in tasks)
            avg_progress = round(total_weight / total_tasks, 1)

        data = {
            "memberName":      member.name,
            "totalTasks":      total_tasks,
            "completedTasks":  completed_tasks,
            "inProgressTasks": in_progress_tasks,
            "todoTasks":       todo_tasks,
            "reviewTasks":     review_tasks,
            "cancelledTasks":  cancelled_tasks,
            "completionRate":  completion_rate,
            "onTimeRate":      on_time_rate,
            "projectsCount":   projects_count,
            "avgProgress":     avg_progress,
        }
        return success(data)


# ═══════════════════════════════════════════════════════════════
# USER STATS  GET /api/users/<id>/stats/
# ═══════════════════════════════════════════════════════════════

class UserStatsView(APIView):
    """GET /api/users/<id>/stats/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, id):                              # ✅ u_id → id
        try:
            user = User.objects.get(id=id, is_deleted=False) # ✅ u_id → id
        except User.DoesNotExist:
            return error("User not found.", status.HTTP_404_NOT_FOUND)

        # tasks assigned to this user
        assigned_tasks    = Task.objects.filter(assign_to__id=id, is_deleted=False)   # ✅
        total_tasks       = assigned_tasks.count()
        completed_tasks   = assigned_tasks.filter(status="done").count()
        in_progress_tasks = assigned_tasks.filter(status="in_progress").count()
        todo_tasks        = assigned_tasks.filter(status="todo").count()
        review_tasks      = assigned_tasks.filter(status="review").count()
        cancelled_tasks   = assigned_tasks.filter(status="cancelled").count()

        # tasks created by this user
        created_tasks = Task.objects.filter(
            created_by__id=id, is_deleted=False                                        # ✅
        ).count()

        # tasks assigned by this user to others
        assigned_by_tasks = Task.objects.filter(
            assign_by__id=id, is_deleted=False                                         # ✅
        ).count()

        # projects created by this user
        projects_created = Project.objects.filter(
            created_by__id=id, is_deleted=False                                        # ✅
        ).count()

        # comments made by this user
        comments_count = Comment.objects.filter(u__id=id).count()                     # ✅

        # completion rate
        completion_rate = (
            round((completed_tasks / total_tasks) * 100, 1)
            if total_tasks > 0 else 0
        )

        # on time rate
        now            = timezone.now()
        tasks_with_due = assigned_tasks.filter(due_date__isnull=False)
        on_time_tasks  = tasks_with_due.filter(
            status="done", due_date__gte=now
        ).count()
        on_time_rate = (
            round((on_time_tasks / tasks_with_due.count()) * 100, 1)
            if tasks_with_due.count() > 0 else 0
        )

        # unread notifications
        unread_notifications = Notification.objects.filter(
            u__id=id, is_read=False, is_deleted__isnull=True                          # ✅
        ).count()

        # avg progress
        STATUS_WEIGHT = {
            "todo": 0, "in_progress": 50,
            "review": 75, "done": 100, "cancelled": 0,
        }
        avg_progress = 0
        if total_tasks > 0:
            total_weight = sum(
                STATUS_WEIGHT.get(t.status, 0) for t in assigned_tasks
            )
            avg_progress = round(total_weight / total_tasks, 1)

        data = {
            "userName":            user.u_name,
            "email":               user.email,
            "role":                user.role,
            "totalAssignedTasks":  total_tasks,
            "completedTasks":      completed_tasks,
            "inProgressTasks":     in_progress_tasks,
            "todoTasks":           todo_tasks,
            "reviewTasks":         review_tasks,
            "cancelledTasks":      cancelled_tasks,
            "createdTasks":        created_tasks,
            "assignedByMe":        assigned_by_tasks,
            "projectsCreated":     projects_created,
            "commentsCount":       comments_count,
            "completionRate":      completion_rate,
            "onTimeRate":          on_time_rate,
            "avgProgress":         avg_progress,
            "unreadNotifications": unread_notifications,
        }
        return success(data)


# ═══════════════════════════════════════════════════════════════
# PROJECT TEAM MEMBER STATS  GET /api/projects/<p_id>/members/stats/
# ═══════════════════════════════════════════════════════════════

class ProjectTeamMemberStatsView(APIView):
    """GET /api/projects/<p_id>/members/stats/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, p_id):                            # ✅ p_id stays same
        try:
            project = Project.objects.get(p_id=p_id, is_deleted=False)  # ✅
        except Project.DoesNotExist:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)

        # get all unique members in this project
        pteam_entries = PTeam.objects.filter(
            p__p_id=p_id                                                  # ✅
        ).select_related("tm").distinct()

        # ✅ fixed — tm uses default id not Tm_id
        member_ids = pteam_entries.values_list(
            "tm__id", flat=True
        ).distinct()

        members_stats = []

        STATUS_WEIGHT = {
            "todo": 0, "in_progress": 50,
            "review": 75, "done": 100, "cancelled": 0,
        }

        for tm_id in member_ids:
            try:
                member = TeamMember.objects.get(id=tm_id)                # ✅
            except TeamMember.DoesNotExist:
                continue

            # tasks for this member in this project
            task_ids = PTeam.objects.filter(
                p__p_id=p_id, tm__id=tm_id                               # ✅
            ).values_list("t__t_id", flat=True)

            tasks             = Task.objects.filter(t_id__in=task_ids, is_deleted=False)
            total_tasks       = tasks.count()
            completed_tasks   = tasks.filter(status="done").count()
            in_progress_tasks = tasks.filter(status="in_progress").count()
            todo_tasks        = tasks.filter(status="todo").count()

            # completion rate
            completion_rate = (
                round((completed_tasks / total_tasks) * 100, 1)
                if total_tasks > 0 else 0
            )

            # avg progress
            avg_progress = 0
            if total_tasks > 0:
                total_weight = sum(
                    STATUS_WEIGHT.get(t.status, 0) for t in tasks
                )
                avg_progress = round(total_weight / total_tasks, 1)

            members_stats.append({
                "id":              member.id,                             # ✅
                "memberName":      member.name,
                "role":            member.role,
                "skills":          member.skills,
                "experience":      member.experience,
                "totalTasks":      total_tasks,
                "completedTasks":  completed_tasks,
                "inProgressTasks": in_progress_tasks,
                "todoTasks":       todo_tasks,
                "completionRate":  completion_rate,
                "avgProgress":     avg_progress,
            })

        data = {
            "projectName":  project.p_name,
            "totalMembers": len(members_stats),
            "membersStats": members_stats,
        }
        return success(data)