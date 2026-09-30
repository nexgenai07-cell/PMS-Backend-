"""
End-to-end auth tests — these hit the *real* endpoints (no force_authenticate)
to verify the actual JWT issuance / validation / blacklist round trip works,
since that is security-critical and must not be taken on faith.
"""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from pms_app.models import User


class RegisterTests(APITestCase):
    def setUp(self):
        self.url = reverse("auth_register")

    def test_register_success(self):
        payload = {
            "u_name": "New Guy", "email": "newguy@test.com",
            "password": "StrongPass123", "role": "member",
        }
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertTrue(response.data["success"])
        self.assertTrue(User.objects.filter(email="newguy@test.com").exists())

    def test_password_is_hashed_not_stored_plain(self):
        payload = {
            "u_name": "New Guy2", "email": "newguy2@test.com",
            "password": "StrongPass123", "role": "member",
        }
        self.client.post(self.url, payload)
        user = User.objects.get(email="newguy2@test.com")
        self.assertNotEqual(user.password, "StrongPass123")

    def test_register_duplicate_email_rejected(self):
        payload = {
            "u_name": "Dup", "email": "dup@test.com",
            "password": "StrongPass123", "role": "member",
        }
        first = self.client.post(self.url, payload)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.client.post(self.url, payload)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_required_fields(self):
        response = self.client.post(self.url, {"email": "incomplete@test.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_password_too_short_rejected(self):
        payload = {
            "u_name": "Shorty", "email": "shorty@test.com",
            "password": "123", "role": "member",
        }
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_invalid_email_format_rejected(self):
        payload = {
            "u_name": "Bad Email", "email": "not-an-email",
            "password": "StrongPass123", "role": "member",
        }
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTests(APITestCase):
    def setUp(self):
        self.url = reverse("auth_login")
        self.user = User.objects.create_user(
            email="login@test.com", u_name="Login Test", password="StrongPass123",
        )

    def test_login_success_returns_tokens(self):
        response = self.client.post(self.url, {"email": "login@test.com", "password": "StrongPass123"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.data["data"]
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertEqual(data["email"], "login@test.com")

    def test_login_wrong_password_rejected(self):
        response = self.client.post(self.url, {"email": "login@test.com", "password": "WrongPassword"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(response.data["success"])

    def test_login_unknown_email_rejected(self):
        response = self.client.post(self.url, {"email": "ghost@test.com", "password": "whatever123"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_inactive_user_rejected(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.url, {"email": "login@test.com", "password": "StrongPass123"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_access_token_actually_authenticates(self):
        login_resp = self.client.post(self.url, {"email": "login@test.com", "password": "StrongPass123"})
        access = login_resp.data["data"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        me_resp = self.client.get(reverse("auth_me"))
        self.assertEqual(me_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(me_resp.data["data"]["email"], "login@test.com")


class TokenRefreshTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="refresh@test.com", u_name="Refresh", password="StrongPass123",
        )
        login = self.client.post(reverse("auth_login"), {"email": "refresh@test.com", "password": "StrongPass123"})
        self.refresh_token = login.data["data"]["refresh"]

    def test_refresh_returns_new_access_token(self):
        response = self.client.post(reverse("token_refresh"), {"refresh": self.refresh_token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_refresh_with_garbage_token_rejected(self):
        response = self.client.post(reverse("token_refresh"), {"refresh": "not-a-real-token"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LogoutTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="logout@test.com", u_name="Logout", password="StrongPass123",
        )
        login = self.client.post(reverse("auth_login"), {"email": "logout@test.com", "password": "StrongPass123"})
        self.access = login.data["data"]["access"]
        self.refresh = login.data["data"]["refresh"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")

    def test_logout_requires_auth(self):
        anon = self.client_class()
        response = anon.post(reverse("auth_logout"), {"refresh": self.refresh})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh_token(self):
        response = self.client.post(reverse("auth_logout"), {"refresh": self.refresh})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        # the blacklisted refresh token must no longer be usable
        anon = self.client_class()
        refresh_attempt = anon.post(reverse("token_refresh"), {"refresh": self.refresh})
        self.assertEqual(refresh_attempt.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_without_refresh_field_errors_gracefully(self):
        response = self.client.post(reverse("auth_logout"), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class MeViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="me@test.com", u_name="Me User", password="StrongPass123",
        )
        self.client.force_authenticate(user=self.user)

    def test_get_requires_auth(self):
        anon = self.client_class()
        response = anon.get(reverse("auth_me"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_returns_current_user(self):
        response = self.client.get(reverse("auth_me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["email"], "me@test.com")

    def test_patch_updates_profile(self):
        response = self.client.patch(reverse("auth_me"), {"u_name": "Updated Name"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.u_name, "Updated Name")

    def test_patch_cannot_change_email_to_existing_one(self):
        User.objects.create_user(email="taken@test.com", u_name="Taken", password="StrongPass123")
        response = self.client.patch(reverse("auth_me"), {"email": "taken@test.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
