import os
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shared_collections.models import (
    Collection,
    CollectionClip,
    CollectionMembership,
)

from .models import Clip

# Production security settings turn on when DEBUG=False (which is the case under
# tests); disable the HTTPS redirect so the test client's http requests aren't 301'd.
# Keep media writes out of the real media/ tree.
_TEST_OVERRIDES = override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix="zenkai-test-media-"),
)


@_TEST_OVERRIDES
class ClipUploadFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="gamer", password="pw12345!")
        self.client.force_login(self.user)

    @mock.patch("clips.views.enqueue_transcode")
    @mock.patch("clips.forms.ClipCreateForm._probe_duration", return_value=42.0)
    def test_upload_creates_pending_clip_and_enqueues(self, _probe, enqueue):
        video = SimpleUploadedFile(
            "clip.mp4", b"\x00\x01fake", content_type="video/mp4"
        )
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                reverse("clip-create"),
                {"title": "Ace", "description": "clutch", "video_file": video},
            )
        self.assertEqual(resp.status_code, 302)
        clip = Clip.objects.get()
        self.assertEqual(clip.status, Clip.Status.PENDING)
        self.assertEqual(clip.uploader, self.user)
        # Enqueue is gated on commit so a rolled-back upload never queues a job.
        enqueue.assert_called_once_with(clip)

    @mock.patch("clips.views.enqueue_transcode")
    @mock.patch("clips.forms.ClipCreateForm._probe_duration", return_value=42.0)
    def test_ajax_upload_returns_redirect_json(self, _probe, enqueue):
        video = SimpleUploadedFile(
            "clip.mp4", b"\x00\x01fake", content_type="video/mp4"
        )
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                reverse("clip-create"),
                {"title": "Ace", "description": "", "video_file": video},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["redirect"], reverse("clip-list"))
        enqueue.assert_called_once()

    @mock.patch("clips.forms.ClipCreateForm._probe_duration", return_value=120.0)
    def test_ajax_upload_invalid_returns_error_json(self, _probe):
        video = SimpleUploadedFile(
            "long.mp4", b"\x00\x01fake", content_type="video/mp4"
        )
        resp = self.client.post(
            reverse("clip-create"),
            {"title": "Long", "description": "", "video_file": video},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("video_file", resp.json()["errors"])
        self.assertFalse(Clip.objects.exists())

    @mock.patch("clips.views.enqueue_transcode")
    @mock.patch("clips.forms.ClipCreateForm._probe_duration", return_value=42.0)
    def test_upload_allows_empty_description(self, _probe, enqueue):
        video = SimpleUploadedFile(
            "clip.mp4", b"\x00\x01fake", content_type="video/mp4"
        )
        resp = self.client.post(
            reverse("clip-create"),
            {"title": "No words needed", "description": "", "video_file": video},
        )
        self.assertEqual(resp.status_code, 302)
        clip = Clip.objects.get()
        self.assertEqual(clip.description, "")

    @mock.patch("clips.forms.ClipCreateForm._probe_duration", return_value=120.0)
    def test_upload_rejected_when_too_long(self, _probe):
        video = SimpleUploadedFile(
            "long.mp4", b"\x00\x01fake", content_type="video/mp4"
        )
        resp = self.client.post(
            reverse("clip-create"),
            {"title": "Long", "description": "too long", "video_file": video},
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertContains(resp, "too long")
        self.assertFalse(Clip.objects.exists())

    @mock.patch("clips.forms.ClipCreateForm._probe_duration", return_value=10.0)
    def test_upload_rejected_for_bad_extension(self, _probe):
        bad = SimpleUploadedFile(
            "clip.exe", b"MZ", content_type="application/octet-stream"
        )
        resp = self.client.post(
            reverse("clip-create"),
            {"title": "Bad", "description": "nope", "video_file": bad},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Clip.objects.exists())


@_TEST_OVERRIDES
class ClipBrowseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="gamer", password="pw12345!")
        self.other = User.objects.create_user(username="mario", password="pw12345!")
        self.client.force_login(self.user)
        self.ace = Clip.objects.create(
            title="Clutch ace",
            description="insane battlefield6 moment",
            uploader=self.user,
            video_file=SimpleUploadedFile("a.mp4", b"x"),
        )
        self.pb = Clip.objects.create(
            title="Speedrun PB",
            description="",
            uploader=self.other,
            video_file=SimpleUploadedFile("b.mp4", b"x"),
        )

    def test_search_filters_by_title(self):
        resp = self.client.get(reverse("clip-list"), {"q": "ace"})
        self.assertContains(resp, "Clutch ace")
        self.assertNotContains(resp, "Speedrun PB")

    def test_search_filters_by_description(self):
        resp = self.client.get(reverse("clip-list"), {"q": "battlefield6"})
        self.assertContains(resp, "Clutch ace")
        self.assertNotContains(resp, "Speedrun PB")

    def test_search_filters_by_uploader(self):
        resp = self.client.get(reverse("clip-list"), {"q": "mario"})
        self.assertContains(resp, "Speedrun PB")
        self.assertNotContains(resp, "Clutch ace")

    def test_blank_search_shows_all(self):
        resp = self.client.get(reverse("clip-list"), {"q": "  "})
        self.assertContains(resp, "Clutch ace")
        self.assertContains(resp, "Speedrun PB")

    def test_detail_page_renders(self):
        resp = self.client.get(reverse("clip-detail", args=[self.ace.pk]))
        self.assertContains(resp, "Clutch ace")
        self.assertContains(resp, "Processing")  # PENDING clip shows status

    def test_status_endpoint_returns_json(self):
        resp = self.client.get(reverse("clip-status", args=[self.ace.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "PENDING", "thumbnail_url": None})

    def test_detail_404_for_missing_clip(self):
        resp = self.client.get(reverse("clip-detail", args=[99999]))
        self.assertEqual(resp.status_code, 404)


@_TEST_OVERRIDES
class ClipDeleteTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw12345!")
        self.intruder = User.objects.create_user(
            username="intruder", password="pw12345!"
        )
        self.clip = Clip.objects.create(
            title="Mine",
            description="",
            uploader=self.owner,
            video_file=SimpleUploadedFile("mine.mp4", b"raw-bytes"),
        )

    def test_owner_can_delete_clip_and_files(self):
        raw_path = self.clip.video_file.path
        self.assertTrue(os.path.exists(raw_path))
        self.client.force_login(self.owner)
        # File cleanup runs on commit (destroy_clip queues it via on_commit), so
        # capture and execute the callbacks to observe the storage delete.
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(reverse("clip-delete", args=[self.clip.pk]))
        self.assertRedirects(resp, reverse("clip-list"))
        self.assertFalse(Clip.objects.filter(pk=self.clip.pk).exists())
        self.assertFalse(os.path.exists(raw_path))

    def test_non_owner_gets_403(self):
        self.client.force_login(self.intruder)
        resp = self.client.post(reverse("clip-delete", args=[self.clip.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Clip.objects.filter(pk=self.clip.pk).exists())

    def test_anonymous_redirected_to_login(self):
        resp = self.client.post(reverse("clip-delete", args=[self.clip.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
        self.assertTrue(Clip.objects.filter(pk=self.clip.pk).exists())

    def test_delete_button_only_for_owner(self):
        self.client.force_login(self.intruder)
        resp = self.client.get(reverse("clip-detail", args=[self.clip.pk]))
        self.assertNotContains(resp, "Delete")
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("clip-detail", args=[self.clip.pk]))
        self.assertContains(resp, "Delete")


@_TEST_OVERRIDES
class TranscodeTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="gamer", password="pw12345!")

    def _make_clip(self):
        return Clip.objects.create(
            title="t",
            description="d",
            uploader=self.user,
            video_file=SimpleUploadedFile("raw.mp4", b"\x00\x01raw"),
        )

    @mock.patch("clips.services.ffmpeg")
    def test_transcode_marks_ready(self, fake_ffmpeg):
        from clips import services

        clip = self._make_clip()

        # Pretend ffmpeg wrote a converted file at the temp output path.
        def fake_run(*a, **k):
            out = fake_ffmpeg.input.return_value.output.call_args[0][0]
            with open(out, "wb") as f:
                f.write(b"converted-bytes")

        fake_ffmpeg.input.return_value.output.return_value.run.side_effect = fake_run

        services.transcode_clip(clip.pk)

        clip.refresh_from_db()
        self.assertEqual(clip.status, Clip.Status.READY)
        self.assertTrue(clip.converted_video_file.name)
        self.assertTrue(clip.thumbnail.name)
        # Raw upload is deleted once the converted file exists.
        self.assertFalse(clip.video_file)

    @mock.patch("clips.services.ffmpeg")
    def test_transcode_stays_ready_if_raw_delete_fails(self, fake_ffmpeg):
        from clips import services

        clip = self._make_clip()

        def fake_run(*a, **k):
            out = fake_ffmpeg.input.return_value.output.call_args[0][0]
            with open(out, "wb") as f:
                f.write(b"converted-bytes")

        fake_ffmpeg.input.return_value.output.return_value.run.side_effect = fake_run

        # Simulate storage failing on the raw-file deletion. The clip is already
        # READY by then, so cleanup is best-effort: no exception should escape
        # and the clip must not be downgraded to FAILED.
        instance = Clip.objects.get(pk=clip.pk)
        instance.video_file.delete = mock.Mock(side_effect=RuntimeError("storage down"))
        with mock.patch("clips.services.Clip.objects.get", return_value=instance):
            services.transcode_clip(clip.pk)

        clip.refresh_from_db()
        self.assertEqual(clip.status, Clip.Status.READY)
        self.assertTrue(clip.converted_video_file.name)
        # Deletion failed, so the raw is leaked but the DB stays consistent with
        # storage (still references the raw that's still there) — not corrupted.
        self.assertTrue(clip.video_file)

    @mock.patch("clips.services.ffmpeg")
    def test_transcode_marks_failed_on_error(self, fake_ffmpeg):
        from clips import services

        clip = self._make_clip()
        # Distinct class so RuntimeError falls through to the generic handler,
        # not the ffmpeg.Error branch.
        fake_ffmpeg.Error = type("FFmpegError", (Exception,), {})
        fake_ffmpeg.input.return_value.output.return_value.run.side_effect = (
            RuntimeError("boom")
        )

        with self.assertRaises(RuntimeError):
            services.transcode_clip(clip.pk)

        clip.refresh_from_db()
        self.assertEqual(clip.status, Clip.Status.FAILED)
        self.assertIn("boom", clip.error_message)


@_TEST_OVERRIDES
class VisibilityGatingTests(TestCase):
    """Step-4 access boundaries: PUBLIC clips stay world-viewable; UNLISTED clips
    are hidden from the home feed, public listings, and detail/status for anyone
    but the uploader and active members."""

    def setUp(self):
        self.uploader = User.objects.create_user("uploader", password="pw")
        self.member = User.objects.create_user("member", password="pw")
        self.outsider = User.objects.create_user("outsider", password="pw")
        self.public = Clip.objects.create(
            title="Public play",
            uploader=self.uploader,
            video_file=SimpleUploadedFile("p.mp4", b"x"),
            visibility=Clip.Visibility.PUBLIC,
        )
        self.unlisted = Clip.objects.create(
            title="Unlisted play",
            uploader=self.uploader,
            video_file=SimpleUploadedFile("u.mp4", b"x"),
            visibility=Clip.Visibility.UNLISTED,
        )

    def _share_unlisted_with_member(self):
        col = Collection.objects.create(name="C", owner=self.uploader)
        membership = CollectionMembership.objects.create(
            collection=col,
            user=self.member,
            status=CollectionMembership.Status.ACTIVE,
        )
        CollectionClip.objects.create(
            collection=col, clip=self.unlisted, added_by=self.uploader
        )
        return col, membership

    # --- home feed -----------------------------------------------------------
    def test_home_feed_hides_unlisted_shows_public(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse("clip-list"))
        self.assertContains(resp, "Public play")
        self.assertNotContains(resp, "Unlisted play")

    # --- uploader listing ----------------------------------------------------
    def test_uploader_sees_own_unlisted_on_their_page(self):
        self.client.force_login(self.uploader)
        resp = self.client.get(reverse("user-clips", args=[self.uploader.username]))
        self.assertContains(resp, "Public play")
        self.assertContains(resp, "Unlisted play")

    def test_other_viewer_sees_only_public_on_listing(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse("user-clips", args=[self.uploader.username]))
        self.assertContains(resp, "Public play")
        self.assertNotContains(resp, "Unlisted play")

    def test_anonymous_sees_only_public_on_listing(self):
        resp = self.client.get(reverse("user-clips", args=[self.uploader.username]))
        self.assertContains(resp, "Public play")
        self.assertNotContains(resp, "Unlisted play")

    # --- detail gate ---------------------------------------------------------
    def test_public_detail_viewable_anonymously(self):
        resp = self.client.get(reverse("clip-detail", args=[self.public.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_unlisted_detail_404_for_anonymous_and_outsider(self):
        resp = self.client.get(reverse("clip-detail", args=[self.unlisted.pk]))
        self.assertEqual(resp.status_code, 404)
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse("clip-detail", args=[self.unlisted.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_unlisted_detail_200_for_uploader_and_active_member(self):
        self._share_unlisted_with_member()
        for user in (self.uploader, self.member):
            self.client.force_login(user)
            resp = self.client.get(reverse("clip-detail", args=[self.unlisted.pk]))
            self.assertEqual(resp.status_code, 200)

    def test_ex_member_loses_detail_access(self):
        _col, membership = self._share_unlisted_with_member()
        self.client.force_login(self.member)
        self.assertEqual(
            self.client.get(
                reverse("clip-detail", args=[self.unlisted.pk])
            ).status_code,
            200,
        )
        membership.delete()
        self.assertEqual(
            self.client.get(
                reverse("clip-detail", args=[self.unlisted.pk])
            ).status_code,
            404,
        )

    # --- status gate ---------------------------------------------------------
    def test_public_status_returns_json_to_anonymous(self):
        resp = self.client.get(reverse("clip-status", args=[self.public.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], Clip.Status.PENDING)

    def test_unlisted_status_404_for_outsider(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse("clip-status", args=[self.unlisted.pk]))
        self.assertEqual(resp.status_code, 404)

    # --- unlisted badge (step 7 polish) --------------------------------------
    def test_unlisted_badge_renders_on_clip_card(self):
        # The badge's title attribute is unique to it, so it proves the badge
        # itself rendered (not just the clip title containing "Unlisted").
        badge = "Only visible in collections"
        self.client.force_login(self.uploader)
        own = self.client.get(reverse("user-clips", args=[self.uploader.username]))
        self.assertContains(own, badge)
        # A public viewer never sees the uploader's unlisted clips, badge included.
        self.client.force_login(self.outsider)
        other = self.client.get(reverse("user-clips", args=[self.uploader.username]))
        self.assertNotContains(other, badge)


@_TEST_OVERRIDES
class OrphanReaperTests(TestCase):
    """Step-8 storage hygiene: the scheduled reaper deletes unreferenced media
    older than the age threshold, and never touches referenced or fresh files."""

    def setUp(self):
        self.user = User.objects.create_user("janitor", password="pw")

    def _save_aged(self, name, age_hours):
        """Save a file under storage and backdate its mtime by age_hours."""
        stored = default_storage.save(name, ContentFile(b"x"))
        old = (timezone.now() - timedelta(hours=age_hours)).timestamp()
        os.utime(default_storage.path(stored), (old, old))
        return stored

    def test_old_orphan_is_deleted(self):
        from clips import services

        name = self._save_aged("clips/raw_uploads/orphan.mp4", age_hours=48)
        deleted = services.reap_orphan_media(min_age_hours=6)
        self.assertEqual(deleted, 1)
        self.assertFalse(default_storage.exists(name))

    def test_referenced_file_is_kept_even_when_old(self):
        from clips import services

        clip = Clip.objects.create(
            title="Real",
            uploader=self.user,
            video_file=SimpleUploadedFile("real.mp4", b"x"),
        )
        old = (timezone.now() - timedelta(hours=48)).timestamp()
        os.utime(default_storage.path(clip.video_file.name), (old, old))
        services.reap_orphan_media(min_age_hours=6)
        self.assertTrue(default_storage.exists(clip.video_file.name))

    def test_recent_orphan_is_kept(self):
        from clips import services

        name = self._save_aged("clips/raw_uploads/fresh.mp4", age_hours=1)
        deleted = services.reap_orphan_media(min_age_hours=6)
        self.assertEqual(deleted, 0)
        self.assertTrue(default_storage.exists(name))
