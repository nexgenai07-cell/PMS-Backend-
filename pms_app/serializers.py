from rest_framework import serializers
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, TeamMember, Project, Task, Comment, Notification, PTeam
from .tokens import email_verification_token


# ─────────────────────────────────────────────
# Auth Serializers
# ─────────────────────────────────────────────

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model  = User
        fields = ["u_name", "email", "password", "role"]

    def create(self, validated_data):
        # New users start INACTIVE until they click the verification link.
        user = User.objects.create_user(**validated_data)
        user.is_active   = False
        user.is_verified = False
        user.save(update_fields=['is_active', 'is_verified'])
        return user


class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email    = (data["email"] or "").strip().lower()
        password = data["password"]

        try:
            user = User.objects.get(email__iexact=email, is_deleted=False)
        except User.DoesNotExist:
            raise serializers.ValidationError({
                "detail": "No account found with this email.",
                "code":   "NO_ACCOUNT",
            })

        if not user.check_password(password):
            raise serializers.ValidationError({
                "detail": "Incorrect password.",
                "code":   "INVALID_PASSWORD",
            })

        if not user.is_verified:
            raise serializers.ValidationError({
                "detail": (
                    "Please verify your email address before logging in. "
                    "Check your inbox for the verification link."
                ),
                "code":   "EMAIL_NOT_VERIFIED",
            })

        if not user.is_active:
            raise serializers.ValidationError({
                "detail": "This account is inactive.",
                "code":   "ACCOUNT_INACTIVE",
            })

        refresh = RefreshToken.for_user(user)
        return {
            "refresh":     str(refresh),
            "access":      str(refresh.access_token),
            "user_id":     user.id,
            "u_id":        user.id,
            "email":       user.email,
            "u_name":      user.u_name,
            "name":        user.u_name,
            "role":        user.role,
            "is_verified": user.is_verified,
        }


class VerifyEmailSerializer(serializers.Serializer):
    """POST /api/auth/verify-email — body: { uid, token }"""
    uid   = serializers.CharField()
    token = serializers.CharField()

    def validate(self, data):
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str

        try:
            decoded = force_str(urlsafe_base64_decode(data["uid"]))
            user_id = int(decoded)
        except (TypeError, ValueError, OverflowError):
            raise serializers.ValidationError({
                "detail": "Invalid verification link.",
                "code":   "INVALID_UID",
            })

        try:
            user = User.objects.get(id=user_id, is_deleted=False)
        except User.DoesNotExist:
            raise serializers.ValidationError({
                "detail": "Invalid verification link.",
                "code":   "USER_NOT_FOUND",
            })

        if not email_verification_token.check_token(user, data["token"]):
            raise serializers.ValidationError({
                "detail": (
                    "This verification link is invalid or has expired. "
                    "Please request a new one."
                ),
                "code":   "TOKEN_INVALID_OR_EXPIRED",
            })

        self.context["user"] = user
        return data


class ResendVerificationSerializer(serializers.Serializer):
    """POST /api/auth/resend-verification — body: { email }"""
    email = serializers.EmailField()

    def validate_email(self, value):
        user = User.objects.filter(
            email__iexact=value, is_deleted=False
        ).first()
        self.context["user"] = user
        return value.lower()

class RequestPasswordChangeSerializer(serializers.Serializer):
    """
    POST /api/auth/request-password-change — body: { current, new }

    We *validate* here but do NOT persist. The actual password change
    happens only when the user clicks the emailed confirmation link.
    """
    current = serializers.CharField(write_only=True)
    new     = serializers.CharField(write_only=True, min_length=8)

    def validate(self, data):
        user = self.context["request"].user
        current = data["current"]
        new     = data["new"]

        if not user.check_password(current):
            raise serializers.ValidationError({
                "detail": "Current password is incorrect.",
                "code":   "INVALID_CURRENT_PASSWORD",
            })

        if current == new:
            raise serializers.ValidationError({
                "detail": "New password must be different from the current one.",
                "code":   "SAME_AS_CURRENT",
            })

        self.context["user"] = user
        return data


class ConfirmPasswordChangeSerializer(serializers.Serializer):
    """
    POST /api/auth/confirm-password-change — body: { uid, token, new_password }
    """
    uid          = serializers.CharField()
    token        = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, data):
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str

        try:
            decoded = force_str(urlsafe_base64_decode(data["uid"]))
            user_id = int(decoded)
        except (TypeError, ValueError, OverflowError):
            raise serializers.ValidationError({
                "detail": "Invalid password-change link.",
                "code":   "INVALID_UID",
            })

        try:
            user = User.objects.get(id=user_id, is_deleted=False)
        except User.DoesNotExist:
            raise serializers.ValidationError({
                "detail": "Invalid password-change link.",
                "code":   "USER_NOT_FOUND",
            })

        from .tokens import password_change_token
        if not password_change_token.check_token(user, data["token"]):
            raise serializers.ValidationError({
                "detail": (
                    "This password-change link is invalid or has expired. "
                    "Please request a new one from your profile page."
                ),
                "code":   "TOKEN_INVALID_OR_EXPIRED",
            })

        self.context["user"] = user
        return data
        
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ["id", "u_name", "email", "role", "is_active",
                  "is_verified", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at", "is_verified"]


# ─────────────────────────────────────────────
# TeamMember Serializers
# ─────────────────────────────────────────────

class TeamMemberSerializer(serializers.ModelSerializer):
    added_by_name = serializers.CharField(source="added_by.u_name", read_only=True)

    class Meta:
        model  = TeamMember
        fields = ["id", "name", "email", "desc", "skills", "role", "added_by",
                  "added_by_name", "qualitifcation", "experience",
                  "updated_at", "is_deleted"]
        read_only_fields = ["id", "updated_at", "added_by"]

    def create(self, validated_data):
        validated_data["added_by"] = self.context["request"].user
        return super().create(validated_data)


# ─────────────────────────────────────────────
# Project Serializers
# ─────────────────────────────────────────────

class ProjectSerializer(serializers.ModelSerializer):
    created_by_name  = serializers.CharField(source="created_by.u_name", read_only=True)
    supervisor_names = serializers.SerializerMethodField()

    class Meta:
        model  = Project
        fields = ["p_id", "p_name", "desc", "priority", "created_by",
                  "created_by_name", "supervisors", "supervisor_names",
                  "deadline", "status", "created_at",
                  "start_at", "updated_at", "is_deleted"]
        read_only_fields = ["p_id", "created_by", "created_at", "updated_at"]

    def get_supervisor_names(self, obj):
        return [u.u_name for u in obj.supervisors.all()]

    def create(self, validated_data):
        request = self.context["request"]
        supervisors = validated_data.pop("supervisors", [])

        is_lead = request.user.role in ("member", "lead")
        is_supervisor = request.user.role in ("manager", "supervisor")

        if is_lead and not supervisors:
            raise serializers.ValidationError({
                "supervisors": (
                    "A Lead must select at least one Supervisor "
                    "when creating a project."
                )
            })

        validated_data["created_by"] = request.user
        project = super().create(validated_data)

        if not supervisors and is_supervisor:
            supervisors = [request.user]

        if supervisors:
            project.supervisors.set(supervisors)

        return project

    def update(self, instance, validated_data):
        supervisors = validated_data.pop("supervisors", None)
        instance = super().update(instance, validated_data)
        if supervisors is not None:
            instance.supervisors.set(supervisors)
        return instance


class ProjectListSerializer(serializers.ModelSerializer):
    supervisor_names = serializers.SerializerMethodField()

    class Meta:
        model  = Project
        fields = ["p_id", "p_name", "desc", "priority", "created_by",
                  "supervisors", "supervisor_names",
                  "deadline", "status", "created_at", "start_at",
                  "updated_at", "is_deleted"]

    def get_supervisor_names(self, obj):
        return [u.u_name for u in obj.supervisors.all()]


# ─────────────────────────────────────────────
# Task Serializers  (MULTI-ASSIGN + SUBTASKS)
# ─────────────────────────────────────────────

class TaskSerializer(serializers.ModelSerializer):
    """
    Full task serializer.

    NEW fields:
      - assignees            : list of TeamMember ids (M2M)
      - assignee_names       : list of TeamMember names
      - subtask_count        : how many (non-deleted) subtasks this task has
      - completed_subtasks   : how many of those are done
      - parent               : parent task id (null for top-level tasks)
    """
    assign_to_name     = serializers.SerializerMethodField()
    assignee_names     = serializers.SerializerMethodField()
    assign_by_name     = serializers.CharField(source="assign_by.u_name", read_only=True)
    created_by_name    = serializers.CharField(source="created_by.u_name", read_only=True)
    project_name       = serializers.CharField(source="p.p_name", read_only=True)
    subtask_count      = serializers.SerializerMethodField()
    completed_subtasks = serializers.SerializerMethodField()

    progress = serializers.IntegerField(
        min_value=0, max_value=100, required=False, default=0,
    )

    class Meta:
        model  = Task
        fields = [
            "t_id", "title", "desc", "status",
            "assign_to", "assign_to_name",
            "assignees", "assignee_names",
            "assign_by", "assign_by_name",
            "created_by", "created_by_name",
            "created_at", "p", "project_name",
            "parent",
            "progress", "priority",
            "due_date", "start_date",
            "subtask_count", "completed_subtasks",
            "update_last", "is_deleted",
        ]
        read_only_fields = [
            "t_id", "created_by", "assign_by", "created_at", "update_last",
        ]

    def get_assign_to_name(self, obj):
        if not obj.assign_to_id:
            return None
        try:
            return obj.assign_to.name
        except Exception:
            return None

    def get_assignee_names(self, obj):
        return [tm.name for tm in obj.assignees.all()]

    def get_subtask_count(self, obj):
        return obj.subtasks.filter(is_deleted=False).count()

    def get_completed_subtasks(self, obj):
        return obj.subtasks.filter(is_deleted=False, status="done").count()

    def create(self, validated_data):
        request = self.context["request"]
        assignees = validated_data.pop("assignees", [])

        validated_data["created_by"] = request.user
        validated_data["assign_by"]  = request.user

        # If no explicit legacy assign_to, sync from first of assignees
        if not validated_data.get("assign_to") and assignees:
            validated_data["assign_to"] = assignees[0]

        task = super().create(validated_data)
        if assignees:
            task.assignees.set(assignees)
        return task

    def update(self, instance, validated_data):
        assignees = validated_data.pop("assignees", None)

        # Keep legacy assign_to in sync when we know the new assignee set.
        if assignees is not None:
            if assignees:
                validated_data["assign_to"] = assignees[0]
            else:
                validated_data["assign_to"] = None

        instance = super().update(instance, validated_data)

        if assignees is not None:
            instance.assignees.set(assignees)

        return instance


class TaskListSerializer(serializers.ModelSerializer):
    """
    Lightweight task serializer for list views. Includes the new
    multi-assign and subtask metadata so the frontend can render
    "+N more" badges and subtask progress chips without extra fetches.
    """
    assign_to_name     = serializers.SerializerMethodField()
    assignee_names     = serializers.SerializerMethodField()
    subtask_count      = serializers.SerializerMethodField()
    completed_subtasks = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "t_id",
            "title",
            "status",
            "priority",
            "due_date",
            "p",
            "assign_to",
            "assign_to_name",
            "assignees",
            "assignee_names",
            "parent",
            "subtask_count",
            "completed_subtasks",
            "progress",
            "desc",
        ]

    def get_assign_to_name(self, obj):
        if not obj.assign_to_id:
            return None
        try:
            return obj.assign_to.name
        except Exception:
            return None

    def get_assignee_names(self, obj):
        return [tm.name for tm in obj.assignees.all()]

    def get_subtask_count(self, obj):
        return obj.subtasks.filter(is_deleted=False).count()

    def get_completed_subtasks(self, obj):
        return obj.subtasks.filter(is_deleted=False, status="done").count()


# ─────────────────────────────────────────────
# Comment Serializers
# ─────────────────────────────────────────────

class CommentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="u.u_name", read_only=True)

    class Meta:
        model  = Comment
        fields = ["c_id", "t", "u", "user_name", "desc", "created_at",
                  "updated_at", "priority", "pin"]
        read_only_fields = ["c_id", "u", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["u"] = self.context["request"].user
        return super().create(validated_data)


# ─────────────────────────────────────────────
# Notification Serializers
# ─────────────────────────────────────────────

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Notification
        fields = ["n_id", "u", "type", "message", "is_read",
                  "read_at", "created_at", "is_deleted"]
        read_only_fields = ["n_id", "u", "read_at", "created_at"]


class PTeamSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="p.p_name", read_only=True)
    task_title   = serializers.CharField(source="t.title",  read_only=True)
    member_name  = serializers.CharField(source="tm.name",  read_only=True)

    class Meta:
        model  = PTeam
        fields = ["pt_id", "p", "project_name", "t", "task_title",
                  "tm", "member_name"]
        read_only_fields = ["pt_id"]


class ProjectStatsSerializer(serializers.Serializer):
    totalTasks      = serializers.IntegerField()
    completedTasks  = serializers.IntegerField()
    inProgressTasks = serializers.IntegerField()
    todoTasks       = serializers.IntegerField()
    completionRate  = serializers.FloatField()
    onTimeRate      = serializers.FloatField()
    membersCount    = serializers.IntegerField()
    avgProgress     = serializers.FloatField()