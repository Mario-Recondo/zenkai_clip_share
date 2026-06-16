import tempfile
import threading
from unittest import skipUnless

from django.contrib.auth.models import AnonymousUser, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings

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
