from django.urls import reverse
from rest_framework import status

from pms_app.models import User
from .base import BaseAPITestCase


class UserListViewTests(BaseAPITestCase):
    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("User_List"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_lists_only_non_deleted_users(self):
        self.other_user.soft_delete()
        response = self.client.get(reverse("User_List"))
        data = self.assertSuccess(response)
        emails = [u["email"] for u in data]
        self.assertIn("manager@example.com", emails)
        self.assertNotIn("other@example.com", emails)

    def test_password_is_never_exposed(self):
        response = self.client.get(reverse("User_List"))
        data = self.assertSuccess(response)
        for user in data:
            self.assertNotIn("password", user)


class UserDetailViewTests(BaseAPITestCase):
    def test_get_existing_user(self):
        url = reverse("Single_User", kwargs={"id": self.member_user.id})
        response = self.client.get(url)
        data = self.assertSuccess(response)
        self.assertEqual(data["email"], "member@example.com")

    def test_get_nonexistent_user_404(self):
        url = reverse("Single_User", kwargs={"id": 999999})
        response = self.client.get(url)
        self.assertApiError(response, status.HTTP_404_NOT_FOUND)

    def test_get_soft_deleted_user_404(self):
        self.member_user.soft_delete()
        url = reverse("Single_User", kwargs={"id": self.member_user.id})
        response = self.client.get(url)
        self.assertApiError(response, status.HTTP_404_NOT_FOUND)

    def test_patch_updates_user(self):
        url = reverse("Single_User", kwargs={"id": self.member_user.id})
        response = self.client.patch(url, {"u_name": "Renamed"})
        data = self.assertSuccess(response)
        self.assertEqual(data["u_name"], "Renamed")

    def test_delete_soft_deletes(self):
        url = reverse("Single_User", kwargs={"id": self.member_user.id})
        response = self.client.delete(url)
        self.assertSuccess(response)
        self.member_user.refresh_from_db()
        self.assertTrue(self.member_user.is_deleted)
        # Soft delete must not hard-delete the row.
        self.assertTrue(User.objects.filter(id=self.member_user.id).exists())
