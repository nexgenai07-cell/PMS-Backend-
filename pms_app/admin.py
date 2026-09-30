from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User  # Replace with your model
from pms_app.models import *
class CustomUserAdmin(UserAdmin):
    model = User
    ordering = ['email']  # or any valid field in your model
    # Optional: Customize displayed fields
    list_display = ['u_name', 'email', 'role','is_staff']

        # This is required to show the Add User form
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('u_name', 'email', 'role', 'password', 'is_staff', 'is_active'),
        }),
    )

admin.site.register(User, CustomUserAdmin)