from django.urls import reverse
from rest_framework import status
from django.utils import timezone

from pms_app.models import Notification
from .base import BaseAPITestCase


class NotificationListViewTests(BaseAPITestCase):
    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("NotificationListView"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_only_returns_own_notifications(self):
        Notification.objects.create(u=self.manager, type="task_assigned", message="for manager")
        Notification.objects.create(u=self.other_user, type="task_assigned", message="for other")
        data = self.assertSuccess(self.client.get(reverse("NotificationListView")))
        messages = [n["message"] for n in data]
        self.assertIn("for manager", messages)
        self.assertNotIn("for other", messages)

    def test_excludes_soft_deleted(self):
        notif = Notification.objects.create(u=self.manager, type="x", message="deleted one")
        notif.is_deleted = timezone.now()
        notif.save()
        data = self.assertSuccess(self.client.get(reverse("NotificationListView")))
        self.assertEqual(data, [])

    def test_newest_first(self):
        n1 = Notification.objects.create(u=self.manager, type="x", message="first")
        n2 = Notification.objects.create(u=self.manager, type="x", message="second")
        data = self.assertSuccess(self.client.get(reverse("NotificationListView")))
        self.assertEqual(data[0]["n_id"], n2.n_id)


class NotificationDetailViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.notif = Notification.objects.create(u=self.manager, type="task_assigned", message="hello")

    def test_get_own_notification(self):
        url = reverse("NotificationDetailView", kwargs={"n_id": self.notif.n_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["message"], "hello")

    def test_cannot_get_other_users_notification(self):
        self.as_user(self.other_user)
        url = reverse("NotificationDetailView", kwargs={"n_id": self.notif.n_id})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_get_missing_404(self):
        url = reverse("NotificationDetailView", kwargs={"n_id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)


class NotificationMarkReadViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.notif = Notification.objects.create(u=self.manager, type="task_assigned", message="hello")

    def test_marks_as_read(self):
        url = reverse("NotificationMarkReadView", kwargs={"n_id": self.notif.n_id})
        self.assertSuccess(self.client.patch(url))
        self.notif.refresh_from_db()
        self.assertTrue(self.notif.is_read)
        self.assertIsNotNone(self.notif.read_at)

    def test_cannot_mark_other_users_notification(self):
        self.as_user(self.other_user)
        url = reverse("NotificationMarkReadView", kwargs={"n_id": self.notif.n_id})
        self.assertApiError(self.client.patch(url), status.HTTP_404_NOT_FOUND)
        self.notif.refresh_from_db()
        self.assertFalse(self.notif.is_read)


class NotificationDeleteViewTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.notif = Notification.objects.create(u=self.manager, type="task_assigned", message="hello")

    def test_delete_is_soft_delete(self):
        url = reverse("NotificationDeleteView", kwargs={"n_id": self.notif.n_id})
        self.assertSuccess(self.client.delete(url))
        self.notif.refresh_from_db()
        self.assertIsNotNone(self.notif.is_deleted)
        self.assertTrue(Notification.objects.filter(n_id=self.notif.n_id).exists())

    def test_cannot_delete_other_users_notification(self):
        self.as_user(self.other_user)
        url = reverse("NotificationDeleteView", kwargs={"n_id": self.notif.n_id})
        self.assertApiError(self.client.delete(url), status.HTTP_404_NOT_FOUND)
