from django.utils import timezone
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.template.loader import render_to_string

from .tokens import email_verification_token, password_change_token
from .serializers import VerifyEmailSerializer, ResendVerificationSerializer

from .models import User, TeamMember, Project, Task, Comment, Notification, PTeam
from .serializers import (
    RegisterSerializer, LoginSerializer, UserSerializer, TeamMemberSerializer,
    ProjectSerializer, ProjectListSerializer, TaskSerializer, TaskListSerializer,
    CommentSerializer, NotificationSerializer, PTeamSerializer, ProjectStatsSerializer,  RequestPasswordChangeSerializer,
    ConfirmPasswordChangeSerializer,
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
    uid   = urlsafe_base64_encode(force_bytes(user.id))
    token = email_verification_token.make_token(user)
    base  = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    return f"{base}/verify-email?uid={uid}&token={token}"


def _send_verification_email(user, verification_link):
    subject = "Verify your AEEL-PMS account"
    context = {
        "user_name":         user.u_name,
        "verification_link": verification_link,
        "year":              timezone.now().year,
    }
    text_body = render_to_string("pms_app/emails/verify_email.txt", context)
    html_body = render_to_string("pms_app/emails/verify_email.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


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

        errors = serializer.errors
        non_field = errors.get('non_field_errors')

        code = None
        detail = None

        if isinstance(non_field, dict):
            raw_code = non_field.get('code')
            raw_detail = non_field.get('detail')
            code = raw_code[0] if isinstance(raw_code, list) and raw_code else raw_code
            detail = raw_detail[0] if isinstance(raw_detail, list) and raw_detail else raw_detail

        elif isinstance(non_field, list) and non_field:
            first = non_field[0]
            if isinstance(first, dict):
                raw_code = first.get('code')
                raw_detail = first.get('detail')
                code = raw_code[0] if isinstance(raw_code, list) else raw_code
                detail = raw_detail[0] if isinstance(raw_detail, list) else raw_detail
            else:
                detail = first

        if not code and isinstance(errors.get('detail'), list) and errors['detail']:
            detail = errors['detail'][0]
        if not code and isinstance(errors.get('code'), list) and errors['code']:
            code = errors['code'][0]

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

        if code in ('INVALID_PASSWORD', 'NO_ACCOUNT',
                    'ACCOUNT_INACTIVE', 'ACCOUNT_DELETED'):
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
    """POST /api/auth/logout/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get("refresh"))
            token.blacklist()
            return success({"message": "Logged out successfully."})
        except Exception as e:
            return error(str(e))


class VerifyEmailView(APIView):
    """POST /api/auth/verify-email/"""
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
    """POST /api/auth/resend-verification/"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        if not serializer.is_valid():
            return error(serializer.errors, status.HTTP_400_BAD_REQUEST)

        user = serializer.context.get("user")

        if user and not user.is_verified and not user.is_deleted:
            try:
                link = _build_verification_link(request, user)
                _send_verification_email(user, link)
            except Exception:
                pass

        return success({
            "message": (
                "If an account exists with that email and is unverified, "
                "a new link has been sent."
            )
        })

# ═══════════════════════════════════════════════════════════════
# PASSWORD CHANGE (email-confirmed)
# ═══════════════════════════════════════════════════════════════

def _build_password_change_link(request, user, new_password):
    """
    Encode {uid, token, new_password} into a frontend URL.

    We embed the new password inside the signed token payload rather than
    storing it server-side, so the flow remains stateless. The link is
    single-use because check_token() invalidates once the user's password
    hash changes (which it does the moment the change is confirmed).
    """
    import json, base64
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes

    uid   = urlsafe_base64_encode(force_bytes(user.id))
    token = password_change_token.make_token(user)

    # base64-encode the new password so it survives URL transmission
    payload = base64.urlsafe_b64encode(json.dumps({"p": new_password}).encode()).decode()

    base = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    return f"{base}/confirm-password-change?uid={uid}&token={token}&p={payload}"


def _send_password_change_email(user, confirm_link):
    subject = "Confirm your AEEL-PMS password change"
    context = {
        "user_name":    user.u_name,
        "confirm_link": confirm_link,
        "year":         timezone.now().year,
    }
    text_body = render_to_string("pms_app/emails/password_change.txt", context)
    html_body = render_to_string("pms_app/emails/password_change.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


class RequestPasswordChangeView(APIView):
    """
    POST /api/auth/request-password-change
    body: { current, new }

    Validates the request, emails a confirmation link, but does NOT
    change the password yet.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RequestPasswordChangeSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return error(serializer.errors, status.HTTP_400_BAD_REQUEST)

        user = serializer.context["user"]
        new_password = serializer.validated_data["new"]

        try:
            link = _build_password_change_link(request, user, new_password)
            _send_password_change_email(user, link)
        except Exception as e:
            return error(
                {"detail": f"Could not send confirmation email: {e}. Please try again."},
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return success({
            "message": (
                "We've emailed you a confirmation link. "
                "Click it to finish changing your password."
            ),
            "email": user.email,
        })


class ConfirmPasswordChangeView(APIView):
    """
    POST /api/auth/confirm-password-change
    body: { uid, token, new_password }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ConfirmPasswordChangeSerializer(data=request.data)
        if not serializer.is_valid():
            return error(serializer.errors, status.HTTP_400_BAD_REQUEST)

        user = serializer.context["user"]
        new_password = serializer.validated_data["new_password"]

        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])

        return success({
            "message": "Password changed successfully. You can now log in with the new password.",
            "email":   user.email,
        })
        
class NotificationUnreadCountView(APIView):
    """GET /api/notifications/unread-count"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(
            u=request.user,
            is_read=False,
            is_deleted__isnull=True,
        ).count()
        return success({"count": count})


class MeView(APIView):
    """GET /api/auth/me/"""
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
        user = request.user
        qs = Project.objects.filter(is_deleted=False)

        if user.role == "admin":
            projects = qs.order_by("-created_at")
            return success(ProjectListSerializer(projects, many=True).data)

        team_member_ids = list(
            TeamMember.objects.filter(
                name__iexact=user.u_name,
                is_deleted=0,
            ).values_list("id", flat=True)
        )

        member_project_ids = list(
            PTeam.objects.filter(
                tm_id__in=team_member_ids
            ).values_list("p_id", flat=True).distinct()
        )

        qs = qs.filter(
            Q(supervisors=user) |
            Q(created_by=user) |
            Q(p_id__in=member_project_ids)
        ).distinct()

        projects = qs.order_by("-created_at")
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

    def _get_project(self, request, p_id):
        try:
            project = Project.objects.get(p_id=p_id, is_deleted=False)
        except Project.DoesNotExist:
            return None

        user = request.user

        if user.role == "admin":
            return project
        if project.created_by_id == user.id:
            return project
        if project.supervisors.filter(id=user.id).exists():
            return project

        team_member_ids = list(
            TeamMember.objects.filter(
                name__iexact=user.u_name,
                is_deleted=0,
            ).values_list("id", flat=True)
        )
        if PTeam.objects.filter(p=project, tm_id__in=team_member_ids).exists():
            return project

        return None

    def get(self, request, p_id):
        project = self._get_project(request, p_id)
        if not project:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)
        return success(ProjectSerializer(project).data)

    def patch(self, request, p_id):
        project = self._get_project(request, p_id)
        if not project:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)
        serializer = ProjectSerializer(project, data=request.data, partial=True,
                                       context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return success(serializer.data)
        return error(serializer.errors)

    def delete(self, request, p_id):
        project = self._get_project(request, p_id)
        if not project:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)
        project.soft_delete()
        return success({"message": "Project deleted."})


class ProjectTasksView(APIView):
    """GET /api/projects/<p_id>/tasks/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, p_id):
        try:
            project = Project.objects.get(p_id=p_id, is_deleted=False)
        except Project.DoesNotExist:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)

        user = request.user
        team_member_ids = list(
            TeamMember.objects.filter(
                name__iexact=user.u_name,
                is_deleted=0,
            ).values_list("id", flat=True)
        )

        authorized = (
            user.role == "admin" or
            project.created_by_id == user.id or
            project.supervisors.filter(id=user.id).exists() or
            PTeam.objects.filter(p=project, tm_id__in=team_member_ids).exists()
        )
        if not authorized:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)

        # Only top-level tasks appear in the project task list.
        tasks = Task.objects.filter(
            p__p_id=p_id, is_deleted=False, parent__isnull=True
        ).order_by("-created_at")
        return success(TaskListSerializer(tasks, many=True).data)


class ProjectStatsView(APIView):
    """GET /api/projects/<p_id>/stats/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, p_id):
        try:
            project = Project.objects.get(p_id=p_id, is_deleted=False)
        except Project.DoesNotExist:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)

        # Stats include subtasks — they represent real work items.
        tasks = Task.objects.filter(p__p_id=p_id, is_deleted=False)

        total_tasks       = tasks.count()
        completed_tasks   = tasks.filter(status="done").count()
        in_progress_tasks = tasks.filter(status="in_progress").count()
        todo_tasks        = tasks.filter(status="todo").count()

        completion_rate = (
            round((completed_tasks / total_tasks) * 100, 1)
            if total_tasks > 0 else 0
        )

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

        members_count = PTeam.objects.filter(
            p__p_id=p_id
        ).values("tm").distinct().count()

        avg_progress = 0
        if total_tasks > 0:
            total_weight = sum((t.progress or 0) for t in tasks)
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
    """GET /api/task   POST /api/task"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tasks = Task.objects.filter(is_deleted=False).order_by("-created_at")

        status_filter   = request.query_params.get("status")
        priority_filter = request.query_params.get("priority")
        assigned_to     = request.query_params.get("assign_to")
        project_id      = request.query_params.get("project")
        parent_param    = request.query_params.get("parent")

        # By default, only top-level tasks (no parent). Pass
        # ?parent=<task_id> to fetch subtasks of a specific task, or
        # ?parent=null for all top-level tasks.
        if parent_param is not None:
            if parent_param in ("", "null", "none"):
                tasks = tasks.filter(parent__isnull=True)
            else:
                try:
                    tasks = tasks.filter(parent_id=int(parent_param))
                except (ValueError, TypeError):
                    tasks = tasks.filter(parent__isnull=True)
        else:
            tasks = tasks.filter(parent__isnull=True)

        if status_filter:
            tasks = tasks.filter(status=status_filter)
        if priority_filter:
            tasks = tasks.filter(priority=priority_filter)
        if assigned_to:
            # Match either the M2M assignees or the legacy assign_to FK.
            tasks = tasks.filter(
                Q(assignees__id=assigned_to) | Q(assign_to__id=assigned_to)
            ).distinct()
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
    """GET / PATCH / DELETE /api/task/<t_id>/"""
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


class TaskSubtasksView(APIView):
    """GET /api/task/<t_id>/subtasks   POST /api/task/<t_id>/subtasks"""
    permission_classes = [IsAuthenticated]

    def get(self, request, t_id):
        try:
            parent = Task.objects.get(t_id=t_id, is_deleted=False)
        except Task.DoesNotExist:
            return error("Task not found.", status.HTTP_404_NOT_FOUND)

        subs = parent.subtasks.filter(is_deleted=False).order_by("-created_at")
        return success(TaskSerializer(subs, many=True).data)

    def post(self, request, t_id):
        try:
            parent = Task.objects.get(t_id=t_id, is_deleted=False)
        except Task.DoesNotExist:
            return error("Task not found.", status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        data["p"]      = parent.p_id
        data["parent"] = parent.t_id

        serializer = TaskSerializer(data=data, context={"request": request})
        if serializer.is_valid():
            sub = serializer.save()
            return success(TaskSerializer(sub).data, status.HTTP_201_CREATED)
        return error(serializer.errors)


class TaskCommentsView(APIView):
    """GET /api/tasks/<t_id>/comments/"""
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
    """PATCH /api/comments/<c_id>/pin/"""
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
    """GET /api/notifications/"""
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
# MEMBER STATS
# ═══════════════════════════════════════════════════════════════

class TeamMemberStatsView(APIView):
    """GET /api/team-members/<id>/stats/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        try:
            member = TeamMember.objects.get(id=id, is_deleted=0)
        except TeamMember.DoesNotExist:
            return error("Team member not found.", status.HTTP_404_NOT_FOUND)

        # Combine M2M + legacy single assignee tasks for this member.
        tasks = Task.objects.filter(
            Q(assignees__id=id) | Q(assign_to__id=id),
            is_deleted=False,
        ).distinct()

        pteam_entries = PTeam.objects.filter(tm__id=id)

        total_tasks       = tasks.count()
        completed_tasks   = tasks.filter(status="done").count()
        in_progress_tasks = tasks.filter(status="in_progress").count()
        todo_tasks        = tasks.filter(status="todo").count()
        review_tasks      = tasks.filter(status="review").count()
        cancelled_tasks   = tasks.filter(status="cancelled").count()

        completion_rate = (
            round((completed_tasks / total_tasks) * 100, 1)
            if total_tasks > 0 else 0
        )

        now            = timezone.now()
        tasks_with_due = tasks.filter(due_date__isnull=False)
        on_time_tasks  = tasks_with_due.filter(
            status="done", due_date__gte=now
        ).count()
        on_time_rate = (
            round((on_time_tasks / tasks_with_due.count()) * 100, 1)
            if tasks_with_due.count() > 0 else 0
        )

        projects_count = pteam_entries.values("p").distinct().count()

        avg_progress = 0
        if total_tasks > 0:
            total_weight = sum((t.progress or 0) for t in tasks)
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
# USER STATS
# ═══════════════════════════════════════════════════════════════

class UserStatsView(APIView):
    """GET /api/users/<id>/stats/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        try:
            user = User.objects.get(id=id, is_deleted=False)
        except User.DoesNotExist:
            return error("User not found.", status.HTTP_404_NOT_FOUND)

        # Personal scope: any task where this user's TeamMember profile
        # appears as a (multi-)assignee.
        tm_ids = list(
            TeamMember.objects.filter(
                name__iexact=user.u_name,
                is_deleted=0,
            ).values_list("id", flat=True)
        )
        assigned_tasks = Task.objects.filter(
            Q(assignees__id__in=tm_ids) | Q(assign_to__id__in=tm_ids),
            is_deleted=False,
        ).distinct()

        total_tasks       = assigned_tasks.count()
        completed_tasks   = assigned_tasks.filter(status="done").count()
        in_progress_tasks = assigned_tasks.filter(status="in_progress").count()
        todo_tasks        = assigned_tasks.filter(status="todo").count()
        review_tasks      = assigned_tasks.filter(status="review").count()
        cancelled_tasks   = assigned_tasks.filter(status="cancelled").count()

        created_tasks = Task.objects.filter(
            created_by__id=id, is_deleted=False
        ).count()

        assigned_by_tasks = Task.objects.filter(
            assign_by__id=id, is_deleted=False
        ).count()

        projects_created = Project.objects.filter(
            created_by__id=id, is_deleted=False
        ).count()

        comments_count = Comment.objects.filter(u__id=id).count()

        completion_rate = (
            round((completed_tasks / total_tasks) * 100, 1)
            if total_tasks > 0 else 0
        )

        now            = timezone.now()
        tasks_with_due = assigned_tasks.filter(due_date__isnull=False)
        on_time_tasks  = tasks_with_due.filter(
            status="done", due_date__gte=now
        ).count()
        on_time_rate = (
            round((on_time_tasks / tasks_with_due.count()) * 100, 1)
            if tasks_with_due.count() > 0 else 0
        )

        unread_notifications = Notification.objects.filter(
            u__id=id, is_read=False, is_deleted__isnull=True
        ).count()

        avg_progress = 0
        if total_tasks > 0:
            total_weight = sum((t.progress or 0) for t in assigned_tasks)
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
# PROJECT TEAM MEMBER STATS
# ═══════════════════════════════════════════════════════════════

class ProjectTeamMemberStatsView(APIView):
    """GET /api/projects/<p_id>/members/stats/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, p_id):
        try:
            project = Project.objects.get(p_id=p_id, is_deleted=False)
        except Project.DoesNotExist:
            return error("Project not found.", status.HTTP_404_NOT_FOUND)

        pteam_entries = PTeam.objects.filter(
            p__p_id=p_id
        ).select_related("tm").distinct()

        member_ids = pteam_entries.values_list(
            "tm__id", flat=True
        ).distinct()

        members_stats = []

        for tm_id in member_ids:
            try:
                member = TeamMember.objects.get(id=tm_id)
            except TeamMember.DoesNotExist:
                continue

            tasks = Task.objects.filter(
                Q(assignees__id=tm_id) | Q(assign_to__id=tm_id),
                p__p_id=p_id,
                is_deleted=False,
            ).distinct()

            total_tasks       = tasks.count()
            completed_tasks   = tasks.filter(status="done").count()
            in_progress_tasks = tasks.filter(status="in_progress").count()
            todo_tasks        = tasks.filter(status="todo").count()

            completion_rate = (
                round((completed_tasks / total_tasks) * 100, 1)
                if total_tasks > 0 else 0
            )

            avg_progress = 0
            if total_tasks > 0:
                total_weight = sum((t.progress or 0) for t in tasks)
                avg_progress = round(total_weight / total_tasks, 1)

            members_stats.append({
                "id":              member.id,
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


# ═══════════════════════════════════════════════════════════════
# LEAD STATS  GET /api/leads/stats/
# ═══════════════════════════════════════════════════════════════

class LeadStatsView(APIView):
    """GET /api/leads/stats/"""
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _compute_task_stats(tasks):
        total = len(tasks)
        completed   = sum(1 for t in tasks if t.status in ('done', 'completed'))
        in_progress = sum(1 for t in tasks if t.status in ('in_progress', 'review'))
        todo        = sum(1 for t in tasks if t.status in ('todo', 'pending', 'planning'))

        completion_rate = round((completed / total) * 100, 1) if total else 0

        avg_progress = 0
        if total:
            total_prog = 0
            for t in tasks:
                if t.progress is not None:
                    total_prog += t.progress
                elif t.status in ('done', 'completed'):
                    total_prog += 100
                elif t.status == 'review':
                    total_prog += 75
                elif t.status == 'in_progress':
                    total_prog += 50
            avg_progress = round(total_prog / total, 1)

        completed_with_due = [
            t for t in tasks
            if t.status in ('done', 'completed') and t.due_date
        ]
        on_time = sum(
            1 for t in completed_with_due
            if t.update_last and t.due_date and t.update_last <= t.due_date
        )
        on_time_rate = (
            round((on_time / len(completed_with_due)) * 100, 1)
            if completed_with_due else 0
        )

        return {
            'total':              total,
            'completed':          completed,
            'in_progress':        in_progress,
            'todo':               todo,
            'completion_rate':    completion_rate,
            'avg_progress':       avg_progress,
            'on_time_rate':       on_time_rate,
            'has_completed_due':  len(completed_with_due) > 0,
        }

    def get(self, request):
        leads = User.objects.filter(
            is_deleted=False,
            role__in=['member', 'developer', 'lead'],
        )

        projects = list(
            Project.objects
                .filter(is_deleted=False)
                .prefetch_related('supervisors')
        )
        project_by_id = {p.p_id: p for p in projects}

        tasks = list(Task.objects.filter(is_deleted=False))
        task_by_id = {t.t_id: t for t in tasks}

        team_members = list(TeamMember.objects.filter(is_deleted=0))

        pteam_entries = list(
            PTeam.objects.select_related('p', 't', 'tm').all()
        )

        tm_by_name = {}
        for tm in team_members:
            key = (tm.name or '').lower().strip()
            if key and key not in tm_by_name:
                tm_by_name[key] = tm

        projects_by_creator = {}
        for p in projects:
            if p.created_by_id:
                projects_by_creator.setdefault(p.created_by_id, []).append(p)

        projects_by_supervisor = {}
        for p in projects:
            for u in p.supervisors.all():
                projects_by_supervisor.setdefault(u.id, []).append(p)

        tm_project_ids = {}
        tm_pteam_task_ids = {}
        for entry in pteam_entries:
            if entry.tm_id is None:
                continue
            tm_id = entry.tm_id
            if entry.p_id is not None:
                tm_project_ids.setdefault(tm_id, set()).add(entry.p_id)
            if entry.t_id is not None:
                tm_pteam_task_ids.setdefault(tm_id, set()).add(entry.t_id)

        # NEW: multi-assign aware — tasks_by_assignee now includes M2M.
        tasks_by_assignee = {}
        for t in tasks:
            if t.assign_to_id is not None:
                tasks_by_assignee.setdefault(t.assign_to_id, set()).add(t.t_id)
            for tm in t.assignees.all():
                tasks_by_assignee.setdefault(tm.id, set()).add(t.t_id)

        results = []

        for user in leads:
            user_id = user.id

            created_projects    = projects_by_creator.get(user_id, [])
            supervised_projects = projects_by_supervisor.get(user_id, [])

            key = (user.u_name or '').lower().strip()
            member = tm_by_name.get(key)
            pteam_projects = []
            if member is not None:
                pids = tm_project_ids.get(member.id, set())
                pteam_projects = [project_by_id[pid] for pid in pids if pid in project_by_id]

            project_map = {}
            for p in created_projects + supervised_projects + pteam_projects:
                project_map[p.p_id] = p
            lead_projects = list(project_map.values())
            lead_project_ids = set(p.p_id for p in lead_projects)

            project_tasks = [t for t in tasks if t.p_id in lead_project_ids]

            personal_task_ids = set()
            if member is not None:
                personal_task_ids |= tasks_by_assignee.get(member.id, set())
                personal_task_ids |= tm_pteam_task_ids.get(member.id, set())
            personal_tasks = [
                task_by_id[tid] for tid in personal_task_ids
                if tid in task_by_id
            ]

            project_stats  = self._compute_task_stats(project_tasks)
            personal_stats = self._compute_task_stats(personal_tasks)

            member_ids = set()
            for t in project_tasks:
                if t.assign_to_id is not None:
                    member_ids.add(t.assign_to_id)
                for tm in t.assignees.all():
                    member_ids.add(tm.id)

            projects_payload = [
                {
                    'p_id':     p.p_id,
                    'p_name':   p.p_name,
                    'desc':     p.desc,
                    'status':   p.status,
                    'priority': p.priority,
                }
                for p in lead_projects
            ]

            results.append({
                'userId':              user_id,
                'u_name':              user.u_name,
                'email':               user.email,
                'role':                user.role,
                'hasTeamMember':       member is not None,
                'teamMemberId':        member.id if member else None,

                'projects':            projects_payload,
                'projectCount':        len(lead_projects),

                'totalTasks':          project_stats['total'],
                'completedTasks':      project_stats['completed'],
                'inProgressTasks':     project_stats['in_progress'],
                'todoTasks':           project_stats['todo'],
                'completionRate':      project_stats['completion_rate'],
                'avgProgress':         project_stats['avg_progress'],
                'onTimeRate':          project_stats['on_time_rate'],
                'hasCompletedWithDue': project_stats['has_completed_due'],

                'personalTotalTasks':          personal_stats['total'],
                'personalCompletedTasks':      personal_stats['completed'],
                'personalInProgressTasks':     personal_stats['in_progress'],
                'personalTodoTasks':           personal_stats['todo'],
                'personalCompletionRate':      personal_stats['completion_rate'],
                'personalAvgProgress':         personal_stats['avg_progress'],
                'personalOnTimeRate':          personal_stats['on_time_rate'],
                'personalHasCompletedWithDue': personal_stats['has_completed_due'],

                'teamSize':            len(member_ids),
                'directAssignedCount': personal_stats['total'],
            })

        results.sort(key=lambda r: (-r['personalCompletionRate'], (r['u_name'] or '').lower()))

        return success(results)