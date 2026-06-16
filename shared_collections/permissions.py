"""Authorization + destructive-action helpers for Collections.

Single source of truth for "who may do what" and for the two destructive paths
(safe in-collection delete, and full destroy). Views call these; templates gate
buttons on the ``can_*`` predicates.

Concurrency note: the destructive helpers lock the clip row with
``select_for_update`` and queue file cleanup via ``transaction.on_commit`` so a
surrounding transaction's rollback can never leave bytes deleted while the row
survives. They require a row-locking backend (PostgreSQL) — enforced at startup
by ``shared_collections.checks``.
"""

import logging

from django.db import transaction
from django.db.models import Q

from clips.models import Clip

from .models import Collection, CollectionClip, CollectionMembership

logger = logging.getLogger(__name__)


# --- Predicates ---------------------------------------------------------------


def can_view(clip, user):
    """Whether ``user`` may view ``clip`` (its detail page / a listing entry).

    PUBLIC clips are world-viewable. UNLISTED clips are restricted to the
    uploader or an active member (incl. owner) of a collection the clip is in.
    """
    if clip.visibility == Clip.Visibility.PUBLIC:
        return True
    if not user.is_authenticated:
        return False
    if clip.uploader_id == user.id:
        return True
    return CollectionClip.objects.filter(
        clip=clip,
        collection__in=Collection.objects.filter(
            Q(owner=user)
            | Q(
                memberships__user=user,
                memberships__status=CollectionMembership.Status.ACTIVE,
            )
        ),
    ).exists()


def can_unlink(collection, user, clip):
    """Whether ``user`` may unlink ``clip`` from ``collection`` (remove the link).

    The owner may unlink any clip from their collection; a member may unlink only
    their own. Callers must first confirm the (collection, clip) link exists
    (link-scoped authorization — see ``can_delete``).
    """
    return user == collection.owner or clip.uploader_id == user.id


def can_delete(collection, user, clip):
    """Whether ``user`` may destructively delete ``clip`` in ``collection``'s context.

    The uploader may always delete their own clip. Otherwise only the owner has a
    delegated path, and only when the uploader opted in (``allow_owner_delete``)
    OR is no longer an active member of the collection.

    PRECONDITION: the caller has already proven the clip is linked to this
    collection. This answers "is this user allowed", NOT "is the clip in the
    collection" — skipping the link check turns a scoped action into a global
    destroy path.
    """
    if clip.uploader_id == user.id:
        return True
    if user != collection.owner:
        return False
    membership = collection.memberships.filter(user=clip.uploader).first()
    if membership is None or membership.status != CollectionMembership.Status.ACTIVE:
        return True  # ex-member (or never-active): owner may clean up
    return membership.allow_owner_delete


# --- Destructive actions ------------------------------------------------------


def _cleanup_files_on_commit(clip_id, files):
    """Queue best-effort storage cleanup to run AFTER the outermost commit.

    Never raises: the DB row is already gone, so a storage hiccup may orphan
    files (the janitor job reclaims them) but must not resurrect the clip or
    mask the caller's flow.
    """

    def cleanup():
        for f in files:
            if not f:
                continue
            try:
                f.delete(save=False)
            except Exception:
                logger.exception(
                    "shared_collections: orphaned media after clip delete (clip_id=%s)",
                    clip_id,
                )

    transaction.on_commit(cleanup)


def destroy_clip(clip):
    """Fully destroy a clip (row + files), cascading its collection links.

    The ONLY full-destroy entry point, so the safe-delete contract can't be
    silently bypassed.
    """
    with transaction.atomic():
        clip = Clip.objects.select_for_update().get(pk=clip.pk)
        files = [clip.video_file, clip.converted_video_file, clip.thumbnail]
        clip_id = clip.pk
        clip.delete()  # cascades CollectionClip rows
        _cleanup_files_on_commit(clip_id, files)


def delete_clip_in_collection(collection, clip):
    """Safe delete: unlink ``clip`` from ``collection``; destroy only if it's the
    clip's sole home (not PUBLIC and not in any other collection).

    Atomic + row-locked so a concurrent "add to another collection" can't race
    the "still shared?" decision. Idempotent: a repeated call unlinks 0 rows.

    PRECONDITION: the caller has verified the (collection, clip) link exists
    (views do this via get_object_or_404). As defence-in-depth we also no-op when
    the link is absent, so a mis-scoped call can never destroy a clip that was
    never in this collection.
    """
    with transaction.atomic():
        clip = Clip.objects.select_for_update().get(pk=clip.pk)
        unlinked, _ = CollectionClip.objects.filter(
            collection=collection, clip=clip
        ).delete()
        if not unlinked:
            return  # clip was not in this collection — nothing to unlink or destroy
        still_shared = (
            clip.visibility == Clip.Visibility.PUBLIC
            or CollectionClip.objects.filter(clip=clip).exists()
        )
        if not still_shared:
            files = [clip.video_file, clip.converted_video_file, clip.thumbnail]
            clip_id = clip.pk
            clip.delete()
            _cleanup_files_on_commit(clip_id, files)
