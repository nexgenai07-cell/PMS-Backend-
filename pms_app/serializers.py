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

        # -------------------------------------------------------------
        # Manually fetch user + check password.
        #
        # We do NOT use Django's authenticate() here because its default
        # ModelBackend returns None for is_active=False users — which
        # would make an unverified user look like a wrong password.
        # -------------------------------------------------------------
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

        # -------------------------------------------------------------
        # Now that password is confirmed correct, check account state.
        # Order matters: unverified is more informative than inactive,
        # so check is_verified BEFORE is_active.
        # -------------------------------------------------------------
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

        # -------------------------------------------------------------
        # All checks passed — issue tokens
        # -------------------------------------------------------------
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
    uid   = serializers.CharField()   # base64 string, decoded in validate()
    token = serializers.CharField()

    def validate(self, data):
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str

        # Decode the base64 uid back to an integer
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
        # Never reveal whether the email exists — same response either way.
        user = User.objects.filter(
            email__iexact=value, is_deleted=False
        ).first()
        self.context["user"] = user
        return value.lower()


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
        fields = ["id", "name", "desc", "skills", "role", "added_by",
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
        # Allow updating supervisors on PATCH too — fixes Issue #7
        # (supervisor not saved when editing an existing project).
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
# Task Serializers
# ─────────────────────────────────────────────

class TaskSerializer(serializers.ModelSerializer):
    assign_to_name  = serializers.CharField(source="assign_to.name",  read_only=True)
    assign_by_name  = serializers.CharField(source="assign_by.u_name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.u_name", read_only=True)
    project_name    = serializers.CharField(source="p.p_name",         read_only=True)

    progress = serializers.IntegerField(
        min_value=0, max_value=100, required=False, default=0,
    )

    class Meta:
        model  = Task
        fields = ["t_id", "title", "desc", "status", "assign_to", "assign_to_name",
                  "assign_by", "assign_by_name", "created_by", "created_by_name",
                  "created_at", "p", "project_name", "progress", "priority", "due_date",
                  "start_date", "update_last", "is_deleted"]
        read_only_fields = ["t_id", "created_by", "assign_by", "created_at", "update_last"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        validated_data["assign_by"]  = self.context["request"].user
        return super().create(validated_data)


class TaskListSerializer(serializers.ModelSerializer):
    """
    Lightweight task serializer for list views.

    - We use SerializerMethodField for `assign_to_name` so the name is
      always read fresh from the FK.
    - We expose `assign_to` (TeamMember id) so the frontend can resolve
      the assignee by id.
    - We expose `p` (Project id) so the frontend can filter tasks by
      project without an extra request per task.
    """

    assign_to_name = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "t_id",
            "title",
            "status",
            "priority",
            "due_date",
            "p",                 # ← NEW: project id
            "assign_to",         # ← FK id
            "assign_to_name",
            "progress",
        ]

    def get_assign_to_name(self, obj):
        if not obj.assign_to_id:
            return None
        try:
            return obj.assign_to.name
        except Exception:
            return None


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