from rest_framework import serializers
from .models import User, TeamMember, Project, Task, Comment, Notification, PTeam

from rest_framework import serializers
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

# class UserSerializer(serializers.ModelSerializer):
#     class Meta:
#         model- User
#         feilds= ('id','username','email')

# ─────────────────────────────────────────────
# Auth Serializers
# ─────────────────────────────────────────────

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model  = User
        fields = ["u_name", "email", "password", "role"]

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data["email"], password=data["password"])
        if not user:
            raise serializers.ValidationError("Invalid credentials.")
        if not user.is_active:
            raise serializers.ValidationError("Account is inactive.")
        refresh = RefreshToken.for_user(user)
        return {
            "refresh" : str(refresh),
            "access"  : str(refresh.access_token),
            "user_id" : user.id,
            "email"   : user.email,
            "role"    : user.role,
        }


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ["id", "u_name", "email", "role", "is_active",
                  "is_verified", "created_at", "updated_at"]
        read_only_fields = ["u_id", "created_at", "updated_at"]


# ─────────────────────────────────────────────
# TeamMember Serializers
# ─────────────────────────────────────────────

class TeamMemberSerializer(serializers.ModelSerializer):
    added_by_name = serializers.CharField(source="added_by.u_name", read_only=True)

    class Meta:
        model  = TeamMember
        fields = ["id", "name", "desc", "skills", "role", "added_by",
                  "added_by_name", "qualitifcation", "experience", "updated_at", "is_deleted"]
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

        # Current DB role values are "manager" (= Supervisor) and "member"
        # (= Lead) — see User.ROLE_CHOICES. Both current and the eventual
        # renamed values are checked here so this keeps working either way.
        is_lead = request.user.role in ("member", "lead")
        is_supervisor = request.user.role in ("manager", "supervisor")

        if is_lead and not supervisors:
            raise serializers.ValidationError({
                "supervisors": "A Lead must select at least one Supervisor when creating a project."
            })

        validated_data["created_by"] = request.user
        project = super().create(validated_data)

        # Supervisor creating a project and picking no one -> becomes the
        # supervisor themself by default.
        if not supervisors and is_supervisor:
            supervisors = [request.user]

        if supervisors:
            project.supervisors.set(supervisors)

        return project


class ProjectListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing projects."""
    class Meta:
        model  = Project
        fields = ["p_id", "p_name","desc", "priority", "created_by", "supervisors",
                  "deadline", "status", "created_at", "start_at", "updated_at","is_deleted"]


# ─────────────────────────────────────────────
# Task Serializers
# ─────────────────────────────────────────────

class TaskSerializer(serializers.ModelSerializer):
    assign_to_name  = serializers.CharField(source="assign_to.name",  read_only=True)
    assign_by_name  = serializers.CharField(source="assign_by.u_name",  read_only=True)
    created_by_name = serializers.CharField(source="created_by.u_name", read_only=True)
    project_name    = serializers.CharField(source="p.p_name",          read_only=True)

    class Meta:
        model  = Task
        fields = ["t_id", "title", "desc", "status", "assign_to", "assign_to_name",
                  "assign_by", "assign_by_name", "created_by", "created_by_name",
                  "created_at", "p", "project_name", "priority", "due_date",
                  "start_date", "update_last", "is_deleted"]
        read_only_fields = ["t_id", "created_by", "assign_by", "created_at", "update_last"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        validated_data["assign_by"]  = self.context["request"].user
        return super().create(validated_data)


class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing tasks."""
    assign_to_name = serializers.CharField(source="assign_to.u_name", read_only=True)

    class Meta:
        model  = Task
        fields = ["t_id", "title", "status", "priority", "due_date", "assign_to_name"]

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
    project_name = serializers.CharField(source="p.p_name",    read_only=True)
    task_title   = serializers.CharField(source="t.title",     read_only=True)
    member_name  = serializers.CharField(source="tm.name",     read_only=True)

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