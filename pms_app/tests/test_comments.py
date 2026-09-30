from django.urls import reverse
from rest_framework import status

from pms_app.models import Comment
from .base import BaseAPITestCase


class CommentListCreateTests(BaseAPITestCase):
    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("CommentListCreateView"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_sets_author_from_request_not_payload(self):
        """`u` is read_only — even if a client tries to post as someone else,
        the comment must be attributed to the authenticated user."""
        payload = {"t": self.task.t_id, "desc": "Looks good", "u": self.other_user.id}
        response = self.client.post(reverse("CommentListCreateView"), payload)
        data = self.assertSuccess(response, status.HTTP_201_CREATED)
        comment = Comment.objects.get(c_id=data["c_id"])
        self.assertEqual(comment.u_id, self.manager.id)

    def test_create_requires_task(self):
        response = self.client.post(reverse("CommentListCreateView"), {"desc": "orphan comment"})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)

    def test_create_requires_desc(self):
        response = self.client.post(reverse("CommentListCreateView"), {"t": self.task.t_id})
        self.assertApiError(response, status.HTTP_400_BAD_REQUEST)

    def test_list_returns_all_comments(self):
        Comment.objects.create(t=self.task, u=self.manager, desc="a")
        Comment.objects.create(t=self.task, u=self.manager, desc="b")
        data = self.assertSuccess(self.client.get(reverse("CommentListCreateView")))
        self.assertEqual(len(data), 2)


class CommentDetailTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.comment = Comment.objects.create(t=self.task, u=self.manager, desc="original text")

    def test_get_existing(self):
        url = reverse("CommentDetailView", kwargs={"c_id": self.comment.c_id})
        data = self.assertSuccess(self.client.get(url))
        self.assertEqual(data["desc"], "original text")

    def test_get_missing_404(self):
        url = reverse("CommentDetailView", kwargs={"c_id": 999999})
        self.assertApiError(self.client.get(url), status.HTTP_404_NOT_FOUND)

    def test_owner_can_edit(self):
        url = reverse("CommentDetailView", kwargs={"c_id": self.comment.c_id})
        data = self.assertSuccess(self.client.patch(url, {"desc": "edited"}))
        self.assertEqual(data["desc"], "edited")

    def test_non_owner_cannot_edit(self):
        self.as_user(self.other_user)
        url = reverse("CommentDetailView", kwargs={"c_id": self.comment.c_id})
        response = self.client.patch(url, {"desc": "hacked"})
        self.assertApiError(response, status.HTTP_403_FORBIDDEN)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.desc, "original text")

    def test_owner_can_delete(self):
        url = reverse("CommentDetailView", kwargs={"c_id": self.comment.c_id})
        self.assertSuccess(self.client.delete(url))
        self.assertFalse(Comment.objects.filter(c_id=self.comment.c_id).exists())

    def test_non_owner_cannot_delete(self):
        self.as_user(self.other_user)
        url = reverse("CommentDetailView", kwargs={"c_id": self.comment.c_id})
        response = self.client.delete(url)
        self.assertApiError(response, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Comment.objects.filter(c_id=self.comment.c_id).exists())


class CommentPinTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.comment = Comment.objects.create(t=self.task, u=self.manager, desc="pin me")

    def test_toggle_pin_on(self):
        url = reverse("CommentPinView", kwargs={"c_id": self.comment.c_id})
        data = self.assertSuccess(self.client.patch(url))
        self.assertTrue(data["pinned"])
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.pin)

    def test_toggle_pin_off_again(self):
        url = reverse("CommentPinView", kwargs={"c_id": self.comment.c_id})
        self.client.patch(url)  # -> True
        data = self.assertSuccess(self.client.patch(url))  # -> False
        self.assertFalse(data["pinned"])

    def test_pin_missing_comment_404(self):
        url = reverse("CommentPinView", kwargs={"c_id": 999999})
        self.assertApiError(self.client.patch(url), status.HTTP_404_NOT_FOUND)
