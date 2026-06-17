import tempfile
import threading
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from clips.models import Clip

from .models import Collection, CollectionClip, CollectionMembership
from .permissions import (
    can_delete,
    can_unlink,
    can_view,
    delete_clip_in_collection,
    destroy_clip,
)

ACTIVE = CollectionMembership.Status.ACTIVE
PENDING = CollectionMembership.Status.PENDING


def make_clip(uploader, visibility=Clip.Visibility.PUBLIC, title="clip"):
    return Clip.objects.create(
        title=title,
        uploader=uploader,
        video_file=SimpleUploadedFile("c.mp4", b"data", content_type="video/mp4"),
        visibility=visibility,
    )


def add_to(collection, clip, added_by=None):
    return CollectionClip.objects.create(
        collection=collection, clip=clip, added_by=added_by or clip.uploader
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CanViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner")
        cls.member = User.objects.create_user("member")
        cls.outsider = User.objects.create_user("outsider")

    def test_public_clip_visible_to_anyone_including_anonymous(self):
        clip = make_clip(self.owner, Clip.Visibility.PUBLIC)
        self.assertTrue(can_view(clip, AnonymousUser()))
        self.assertTrue(can_view(clip, self.outsider))

    def test_unlisted_hidden_from_anonymous_and_outsiders(self):
        clip = make_clip(self.member, Clip.Visibility.UNLISTED)
        self.assertFalse(can_view(clip, AnonymousUser()))
        self.assertFalse(can_view(clip, self.outsider))

    def test_unlisted_visible_to_uploader(self):
        clip = make_clip(self.member, Clip.Visibility.UNLISTED)
        self.assertTrue(can_view(clip, self.member))

    def test_unlisted_visible_to_active_member_and_owner(self):
        clip = make_clip(self.member, Clip.Visibility.UNLISTED)
        col = Collection.objects.create(name="C", owner=self.owner)
        CollectionMembership.objects.create(
            collection=col, user=self.member, status=ACTIVE
        )
        add_to(col, clip)
        self.assertTrue(can_view(clip, self.owner))
        self.assertTrue(can_view(clip, self.member))
        self.assertFalse(can_view(clip, self.outsider))

    def test_pending_member_cannot_view_unlisted(self):
        clip = make_clip(self.owner, Clip.Visibility.UNLISTED)
        col = Collection.objects.create(name="C", owner=self.owner)
        CollectionMembership.objects.create(
            collection=col, user=self.member, status=PENDING
        )
        add_to(col, clip)
        self.assertFalse(can_view(clip, self.member))

    def test_ex_member_loses_view_after_membership_ends(self):
        clip = make_clip(self.owner, Clip.Visibility.UNLISTED)
        col = Collection.objects.create(name="C", owner=self.owner)
        m = CollectionMembership.objects.create(
            collection=col, user=self.member, status=ACTIVE
        )
        add_to(col, clip)
        self.assertTrue(can_view(clip, self.member))
        m.delete()
        self.assertFalse(can_view(clip, self.member))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PermissionMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner")
        cls.member = User.objects.create_user("member")
        cls.outsider = User.objects.create_user("outsider")

    def setUp(self):
        self.col = Collection.objects.create(name="C", owner=self.owner)
        self.membership = CollectionMembership.objects.create(
            collection=self.col, user=self.member, status=ACTIVE
        )
        self.member_clip = make_clip(self.member)
        add_to(self.col, self.member_clip)

    # can_unlink
    def test_owner_can_unlink_any_clip(self):
        self.assertTrue(can_unlink(self.col, self.owner, self.member_clip))

    def test_uploader_can_unlink_own_clip(self):
        self.assertTrue(can_unlink(self.col, self.member, self.member_clip))

    def test_non_owner_non_uploader_cannot_unlink(self):
        self.assertFalse(can_unlink(self.col, self.outsider, self.member_clip))

    # can_delete
    def test_uploader_can_delete_own_clip(self):
        self.assertTrue(can_delete(self.col, self.member, self.member_clip))

    def test_member_cannot_delete_another_members_clip(self):
        other_member = User.objects.create_user("other_member")
        CollectionMembership.objects.create(
            collection=self.col, user=other_member, status=ACTIVE
        )
        self.assertFalse(can_delete(self.col, other_member, self.member_clip))

    def test_owner_cannot_delete_active_members_clip_by_default(self):
        self.assertFalse(can_delete(self.col, self.owner, self.member_clip))

    def test_owner_can_delete_when_member_opted_in(self):
        self.membership.allow_owner_delete = True
        self.membership.save()
        self.assertTrue(can_delete(self.col, self.owner, self.member_clip))

    def test_owner_can_delete_ex_members_clip(self):
        self.membership.delete()  # member left / was removed
        self.assertTrue(can_delete(self.col, self.owner, self.member_clip))

    def test_owner_can_delete_pending_members_clip(self):
        self.membership.status = PENDING
        self.membership.save()
        self.assertTrue(can_delete(self.col, self.owner, self.member_clip))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SafeDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner")

    def test_unlink_public_clip_keeps_the_row(self):
        clip = make_clip(self.owner, Clip.Visibility.PUBLIC)
        col = Collection.objects.create(name="A", owner=self.owner)
        add_to(col, clip)
        delete_clip_in_collection(col, clip)
        self.assertTrue(Clip.objects.filter(pk=clip.pk).exists())
        self.assertFalse(
            CollectionClip.objects.filter(collection=col, clip=clip).exists()
        )

    def test_unlink_multi_collection_unlisted_clip_keeps_the_row(self):
        clip = make_clip(self.owner, Clip.Visibility.UNLISTED)
        col_a = Collection.objects.create(name="A", owner=self.owner)
        col_b = Collection.objects.create(name="B", owner=self.owner)
        add_to(col_a, clip)
        add_to(col_b, clip)
        delete_clip_in_collection(col_a, clip)
        self.assertTrue(Clip.objects.filter(pk=clip.pk).exists())
        self.assertFalse(
            CollectionClip.objects.filter(collection=col_a, clip=clip).exists()
        )
        self.assertTrue(
            CollectionClip.objects.filter(collection=col_b, clip=clip).exists()
        )

    def test_sole_home_unlisted_clip_is_destroyed(self):
        clip = make_clip(self.owner, Clip.Visibility.UNLISTED)
        col = Collection.objects.create(name="A", owner=self.owner)
        add_to(col, clip)
        delete_clip_in_collection(col, clip)
        self.assertFalse(Clip.objects.filter(pk=clip.pk).exists())

    def test_repeated_delete_is_idempotent(self):
        clip = make_clip(self.owner, Clip.Visibility.PUBLIC)
        col = Collection.objects.create(name="A", owner=self.owner)
        add_to(col, clip)
        delete_clip_in_collection(col, clip)
        delete_clip_in_collection(col, clip)  # no-op, must not raise
        self.assertTrue(Clip.objects.filter(pk=clip.pk).exists())

    def test_delete_on_clip_with_no_link_does_not_destroy(self):
        # Mis-scoped call: an UNLISTED clip not in this collection (no links at all)
        # must NOT be destroyed — the unlink removed 0 rows, so it's a no-op.
        clip = make_clip(self.owner, Clip.Visibility.UNLISTED)
        col = Collection.objects.create(name="A", owner=self.owner)
        delete_clip_in_collection(col, clip)
        self.assertTrue(Clip.objects.filter(pk=clip.pk).exists())

    def test_delete_on_unlinked_clip_leaves_other_collections_intact(self):
        # Clip lives in other_col; calling delete for col (where it isn't) is a no-op.
        clip = make_clip(self.owner, Clip.Visibility.UNLISTED)
        other_col = Collection.objects.create(name="Other", owner=self.owner)
        col = Collection.objects.create(name="A", owner=self.owner)
        add_to(other_col, clip)
        delete_clip_in_collection(col, clip)
        self.assertTrue(Clip.objects.filter(pk=clip.pk).exists())
        self.assertTrue(
            CollectionClip.objects.filter(collection=other_col, clip=clip).exists()
        )

    def test_destroy_clip_removes_row_and_links(self):
        clip = make_clip(self.owner, Clip.Visibility.PUBLIC)
        col = Collection.objects.create(name="A", owner=self.owner)
        add_to(col, clip)
        destroy_clip(clip)
        self.assertFalse(Clip.objects.filter(pk=clip.pk).exists())
        self.assertEqual(CollectionClip.objects.filter(clip_id=clip.pk).count(), 0)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
@skipUnless(connection.vendor == "postgresql", "row-level locking requires PostgreSQL")
class ConcurrencyTests(TransactionTestCase):
    def test_concurrent_safe_delete_and_add_never_leaves_torn_state(self):
        """A safe-delete racing an add-to-another-collection must never destroy a
        clip that ends up linked elsewhere, nor leave a link to a destroyed clip.

        select_for_update serializes the two on the clip row, so exactly one of
        these outcomes holds: (a) add wins -> clip survives, linked to B, unlinked
        from A; or (b) delete wins -> clip destroyed, no links anywhere.
        """
        owner = User.objects.create_user("owner")
        clip = make_clip(owner, Clip.Visibility.UNLISTED)
        col_a = Collection.objects.create(name="A", owner=owner)
        col_b = Collection.objects.create(name="B", owner=owner)
        add_to(col_a, clip)
        clip_id = clip.pk

        start = threading.Barrier(2)
        errors = []

        def do_delete():
            start.wait()
            try:
                delete_clip_in_collection(col_a, clip)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        def do_add():
            start.wait()
            try:
                with transaction.atomic():
                    Clip.objects.select_for_update().get(pk=clip_id)
                    CollectionClip.objects.get_or_create(
                        collection=col_b, clip_id=clip_id, defaults={"added_by": owner}
                    )
            except Clip.DoesNotExist:
                pass  # delete won the race and destroyed the clip first
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=do_delete), threading.Thread(target=do_add)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"thread errors: {errors}")

        if Clip.objects.filter(pk=clip_id).exists():
            # add won: clip linked to B, unlinked from A
            self.assertTrue(
                CollectionClip.objects.filter(
                    clip_id=clip_id, collection=col_b
                ).exists()
            )
            self.assertFalse(
                CollectionClip.objects.filter(
                    clip_id=clip_id, collection=col_a
                ).exists()
            )
        else:
            # delete won: no dangling links to a destroyed clip
            self.assertEqual(CollectionClip.objects.filter(clip_id=clip_id).count(), 0)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CoreLoopViewTests(TestCase):
    """Step-3 view tests: create / list / detail gate / upload / add / unlink /
    safe-delete / delete-collection."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", password="pw")
        cls.member = User.objects.create_user("member", password="pw")
        cls.outsider = User.objects.create_user("outsider", password="pw")

    def setUp(self):
        self.col = Collection.objects.create(name="C", owner=self.owner)
        self.membership = CollectionMembership.objects.create(
            collection=self.col, user=self.member, status=ACTIVE
        )

    # --- detail gate ---------------------------------------------------------
    def test_non_member_gets_404_on_detail(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse("collection-detail", args=[self.col.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_active_member_and_owner_get_200_on_detail(self):
        for user in (self.owner, self.member):
            self.client.force_login(user)
            resp = self.client.get(reverse("collection-detail", args=[self.col.pk]))
            self.assertEqual(resp.status_code, 200)

    def test_pending_member_gets_404_on_detail(self):
        self.membership.status = PENDING
        self.membership.save()
        self.client.force_login(self.member)
        resp = self.client.get(reverse("collection-detail", args=[self.col.pk]))
        self.assertEqual(resp.status_code, 404)

    # --- list ----------------------------------------------------------------
    def test_list_shows_owned_and_joined_only(self):
        other = Collection.objects.create(name="Other", owner=self.outsider)
        self.client.force_login(self.member)
        resp = self.client.get(reverse("collection-list"))
        names = [c.name for c in resp.context["collections"]]
        self.assertIn("C", names)
        self.assertNotIn(other.name, names)

    def test_list_shows_clip_and_member_counts(self):
        add_to(self.col, make_clip(self.member))
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("collection-list"))
        # 1 clip, and 2 members (owner + the one active member).
        self.assertContains(resp, "1 clip")
        self.assertContains(resp, "2 members")

    # --- create --------------------------------------------------------------
    def test_create_sets_owner_to_request_user(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            reverse("collection-create"), {"name": "Squad", "description": ""}
        )
        created = Collection.objects.get(name="Squad")
        self.assertEqual(created.owner, self.member)
        self.assertRedirects(resp, reverse("collection-detail", args=[created.pk]))

    # --- upload-into-collection ----------------------------------------------
    @patch("shared_collections.views.enqueue_transcode")
    @patch("clips.forms.ClipCreateForm._probe_duration", return_value=10.0)
    def test_upload_creates_unlisted_clip_linked_and_enqueues(self, _probe, enqueue):
        self.client.force_login(self.member)
        video = SimpleUploadedFile("c.mp4", b"data", content_type="video/mp4")
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                reverse("collection-upload", args=[self.col.pk]),
                {"title": "Play", "description": "", "video_file": video},
            )
        clip = Clip.objects.get(title="Play")
        self.assertEqual(clip.uploader, self.member)
        self.assertEqual(clip.visibility, Clip.Visibility.UNLISTED)
        self.assertTrue(
            CollectionClip.objects.filter(collection=self.col, clip=clip).exists()
        )
        enqueue.assert_called_once_with(clip)
        self.assertRedirects(resp, reverse("collection-detail", args=[self.col.pk]))

    @patch("shared_collections.views.enqueue_transcode")
    @patch("clips.forms.ClipCreateForm._probe_duration", return_value=10.0)
    def test_upload_post_to_home_makes_clip_public(self, _probe, _enqueue):
        self.client.force_login(self.member)
        video = SimpleUploadedFile("c.mp4", b"data", content_type="video/mp4")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("collection-upload", args=[self.col.pk]),
                {
                    "title": "Public play",
                    "description": "",
                    "video_file": video,
                    "post_to_home": "on",
                },
            )
        clip = Clip.objects.get(title="Public play")
        self.assertEqual(clip.visibility, Clip.Visibility.PUBLIC)
        # Still linked to the collection as well as posted to the feed.
        self.assertTrue(
            CollectionClip.objects.filter(collection=self.col, clip=clip).exists()
        )

    # --- add existing own clip -----------------------------------------------
    def test_member_can_add_own_clip(self):
        clip = make_clip(self.member)
        self.client.force_login(self.member)
        self.client.post(
            reverse("collection-add-clip", args=[self.col.pk]), {"clip": clip.pk}
        )
        self.assertTrue(
            CollectionClip.objects.filter(collection=self.col, clip=clip).exists()
        )

    def test_member_cannot_add_someone_elses_clip(self):
        others_clip = make_clip(self.outsider)
        self.client.force_login(self.member)
        resp = self.client.post(
            reverse("collection-add-clip", args=[self.col.pk]),
            {"clip": others_clip.pk},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(CollectionClip.objects.filter(clip=others_clip).exists())

    # --- unlink --------------------------------------------------------------
    def test_remove_clip_unlinks_but_keeps_row(self):
        clip = make_clip(self.member, Clip.Visibility.UNLISTED)
        add_to(self.col, clip)
        self.client.force_login(self.member)
        self.client.post(reverse("collection-remove-clip", args=[self.col.pk, clip.pk]))
        self.assertTrue(Clip.objects.filter(pk=clip.pk).exists())
        self.assertFalse(
            CollectionClip.objects.filter(collection=self.col, clip=clip).exists()
        )

    def test_remove_clip_requires_can_unlink(self):
        clip = make_clip(self.member)
        add_to(self.col, clip)
        stranger = User.objects.create_user("stranger", password="pw")
        CollectionMembership.objects.create(
            collection=self.col, user=stranger, status=ACTIVE
        )
        self.client.force_login(stranger)
        resp = self.client.post(
            reverse("collection-remove-clip", args=[self.col.pk, clip.pk])
        )
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(
            CollectionClip.objects.filter(collection=self.col, clip=clip).exists()
        )

    # --- safe-delete via the view --------------------------------------------
    def test_delete_clip_destroys_sole_home(self):
        clip = make_clip(self.member, Clip.Visibility.UNLISTED)
        add_to(self.col, clip)
        self.client.force_login(self.member)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("collection-delete-clip", args=[self.col.pk, clip.pk])
            )
        self.assertFalse(Clip.objects.filter(pk=clip.pk).exists())

    def test_delete_clip_link_scoped_boundary(self):
        # A clip that lives only in another collection must not be destroyable
        # through this one — even by a caller who would otherwise pass can_delete.
        other = Collection.objects.create(name="Other", owner=self.owner)
        clip = make_clip(self.owner, Clip.Visibility.UNLISTED)
        add_to(other, clip)
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("collection-delete-clip", args=[self.col.pk, clip.pk])
        )
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Clip.objects.filter(pk=clip.pk).exists())
        self.assertTrue(
            CollectionClip.objects.filter(collection=other, clip=clip).exists()
        )

    # --- delete collection ---------------------------------------------------
    def test_delete_collection_unlinks_clips_without_destroying(self):
        clip = make_clip(self.member, Clip.Visibility.UNLISTED)
        add_to(self.col, clip)
        self.client.force_login(self.owner)
        self.client.post(reverse("collection-delete", args=[self.col.pk]))
        self.assertFalse(Collection.objects.filter(pk=self.col.pk).exists())
        self.assertTrue(Clip.objects.filter(pk=clip.pk).exists())
        self.assertEqual(CollectionClip.objects.filter(clip=clip).count(), 0)

    def test_only_owner_can_delete_collection(self):
        self.client.force_login(self.member)
        resp = self.client.post(reverse("collection-delete", args=[self.col.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Collection.objects.filter(pk=self.col.pk).exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CollectionAwareClipDeleteTests(TestCase):
    """The My-clips ClipDeleteView routes through destroy_clip and offers the
    non-destructive 'unpublish' path for clips that live in a collection."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", password="pw")

    def test_unpublish_keeps_clip_in_collection_and_sets_unlisted(self):
        clip = make_clip(self.owner, Clip.Visibility.PUBLIC)
        col = Collection.objects.create(name="C", owner=self.owner)
        add_to(col, clip)
        self.client.force_login(self.owner)
        self.client.post(
            reverse("clip-delete", args=[clip.pk]), {"action": "unpublish"}
        )
        clip.refresh_from_db()
        self.assertEqual(clip.visibility, Clip.Visibility.UNLISTED)
        self.assertTrue(
            CollectionClip.objects.filter(collection=col, clip=clip).exists()
        )

    def test_delete_everywhere_destroys_and_unlinks(self):
        clip = make_clip(self.owner, Clip.Visibility.PUBLIC)
        col = Collection.objects.create(name="C", owner=self.owner)
        add_to(col, clip)
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("clip-delete", args=[clip.pk]),
                {"action": "delete_everywhere"},
            )
        self.assertFalse(Clip.objects.filter(pk=clip.pk).exists())
        self.assertEqual(CollectionClip.objects.filter(clip=clip).count(), 0)

    def test_clip_in_no_collection_is_destroyed(self):
        clip = make_clip(self.owner, Clip.Visibility.PUBLIC)
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("clip-delete", args=[clip.pk]),
                {"action": "delete_everywhere"},
            )
        self.assertFalse(Clip.objects.filter(pk=clip.pk).exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MembershipLifecycleViewTests(TestCase):
    """Step-5 sharing: invite by username, accept / decline, leave, remove-member."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", password="pw")
        cls.invitee = User.objects.create_user("invitee", password="pw")
        cls.outsider = User.objects.create_user("outsider", password="pw")

    def setUp(self):
        self.col = Collection.objects.create(name="C", owner=self.owner)

    def _membership(self):
        return CollectionMembership.objects.filter(
            collection=self.col, user=self.invitee
        ).first()

    # --- invite --------------------------------------------------------------
    def test_owner_invites_by_username_creates_pending(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("collection-invite", args=[self.col.pk]),
            {"username": "invitee"},
        )
        m = self._membership()
        self.assertIsNotNone(m)
        self.assertEqual(m.status, PENDING)

    def test_non_owner_cannot_invite(self):
        self.client.force_login(self.invitee)
        resp = self.client.post(
            reverse("collection-invite", args=[self.col.pk]),
            {"username": "outsider"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(
            CollectionMembership.objects.filter(collection=self.col).exists()
        )

    def test_self_invite_rejected(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("collection-invite", args=[self.col.pk]),
            {"username": "owner"},
        )
        self.assertFalse(
            CollectionMembership.objects.filter(
                collection=self.col, user=self.owner
            ).exists()
        )

    def test_duplicate_invite_does_not_create_second_row(self):
        CollectionMembership.objects.create(
            collection=self.col, user=self.invitee, status=PENDING
        )
        self.client.force_login(self.owner)
        self.client.post(
            reverse("collection-invite", args=[self.col.pk]),
            {"username": "invitee"},
        )
        self.assertEqual(
            CollectionMembership.objects.filter(
                collection=self.col, user=self.invitee
            ).count(),
            1,
        )

    # --- accept / decline ----------------------------------------------------
    def test_accept_sets_active_and_joined_at(self):
        CollectionMembership.objects.create(
            collection=self.col, user=self.invitee, status=PENDING
        )
        self.client.force_login(self.invitee)
        resp = self.client.post(reverse("invite-accept", args=[self.col.pk]))
        m = self._membership()
        self.assertEqual(m.status, ACTIVE)
        self.assertIsNotNone(m.joined_at)
        self.assertRedirects(resp, reverse("collection-detail", args=[self.col.pk]))

    def test_decline_deletes_the_invite(self):
        CollectionMembership.objects.create(
            collection=self.col, user=self.invitee, status=PENDING
        )
        self.client.force_login(self.invitee)
        self.client.post(reverse("invite-decline", args=[self.col.pk]))
        self.assertIsNone(self._membership())

    def test_accept_404_when_no_pending_invite(self):
        self.client.force_login(self.invitee)
        resp = self.client.post(reverse("invite-accept", args=[self.col.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_my_invites_lists_pending_only(self):
        CollectionMembership.objects.create(
            collection=self.col, user=self.invitee, status=PENDING
        )
        active_col = Collection.objects.create(name="Active", owner=self.owner)
        CollectionMembership.objects.create(
            collection=active_col, user=self.invitee, status=ACTIVE
        )
        self.client.force_login(self.invitee)
        resp = self.client.get(reverse("my-invites"))
        self.assertContains(resp, "C")
        self.assertNotContains(resp, "Active")

    # --- leave ---------------------------------------------------------------
    def test_active_member_can_leave(self):
        CollectionMembership.objects.create(
            collection=self.col, user=self.invitee, status=ACTIVE
        )
        self.client.force_login(self.invitee)
        resp = self.client.post(reverse("collection-leave", args=[self.col.pk]))
        self.assertIsNone(self._membership())
        self.assertRedirects(resp, reverse("collection-list"))

    def test_owner_cannot_leave(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("collection-leave", args=[self.col.pk]))
        self.assertEqual(resp.status_code, 404)

    # --- remove member -------------------------------------------------------
    def test_owner_removes_member_clip_stays_and_owner_gains_delete(self):
        CollectionMembership.objects.create(
            collection=self.col, user=self.invitee, status=ACTIVE
        )
        clip = make_clip(self.invitee, Clip.Visibility.UNLISTED)
        add_to(self.col, clip)
        self.client.force_login(self.owner)
        self.client.post(
            reverse("collection-remove-member", args=[self.col.pk, self.invitee.pk])
        )
        self.assertIsNone(self._membership())
        # Ex-member's clip stays linked; owner now passes can_delete over it (#9).
        self.assertTrue(
            CollectionClip.objects.filter(collection=self.col, clip=clip).exists()
        )
        self.assertTrue(can_delete(self.col, self.owner, clip))

    def test_non_owner_cannot_remove_member(self):
        CollectionMembership.objects.create(
            collection=self.col, user=self.invitee, status=ACTIVE
        )
        self.client.force_login(self.invitee)
        resp = self.client.post(
            reverse("collection-remove-member", args=[self.col.pk, self.owner.pk])
        )
        self.assertEqual(resp.status_code, 404)

    # --- allow_owner_delete toggle (step 6) ----------------------------------
    def test_member_opts_owner_in_then_out(self):
        m = CollectionMembership.objects.create(
            collection=self.col, user=self.invitee, status=ACTIVE
        )
        clip = make_clip(self.invitee, Clip.Visibility.UNLISTED)
        add_to(self.col, clip)
        self.assertFalse(can_delete(self.col, self.owner, clip))  # default off

        self.client.force_login(self.invitee)
        self.client.post(
            reverse("membership-settings", args=[self.col.pk]),
            {"allow_owner_delete": "on"},
        )
        m.refresh_from_db()
        self.assertTrue(m.allow_owner_delete)
        self.assertTrue(can_delete(self.col, self.owner, clip))

        # Unchecked checkbox sends no value -> opts the owner back out.
        self.client.post(reverse("membership-settings", args=[self.col.pk]), {})
        m.refresh_from_db()
        self.assertFalse(m.allow_owner_delete)
        self.assertFalse(can_delete(self.col, self.owner, clip))

    def test_owner_cannot_use_membership_settings(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("membership-settings", args=[self.col.pk]),
            {"allow_owner_delete": "on"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_non_member_cannot_use_membership_settings(self):
        self.client.force_login(self.outsider)
        resp = self.client.post(
            reverse("membership-settings", args=[self.col.pk]),
            {"allow_owner_delete": "on"},
        )
        self.assertEqual(resp.status_code, 404)
