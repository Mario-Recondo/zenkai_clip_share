"""Authorization + destructive-action helpers for Collections.

Single source of truth for "who may do what" within a collection and for the
safe in-collection delete. Views call these; templates gate buttons on the
``can_*`` predicates. The base clip-visibility rule and the full-destroy path
live on the ``clips`` side (``Clip.is_viewable_by`` and ``clips.services``);
collections only *adds* an access grant (registered via ``clips.access``), so
the dependency stays one-directional (feature → domain).

Concurrency note: ``delete_clip_in_collection`` locks the clip row with
``select_for_update`` and queues file cleanup via ``transaction.on_commit`` so a
surrounding transaction's rollback can never leave bytes deleted while the row
survives. It requires a row-locking backend (PostgreSQL) — enforced at startup
by ``shared_collections.checks``.
"""

from django.db import transaction
from django.db.models import Q

from clips.models import Clip
from clips.services import cleanup_clip_files_on_commit

from .models import Collection, CollectionClip, CollectionMembership

# --- View-access provider -----------------------------------------------------


def grants_view_via_collection(clip, user):
    """Whether ``user`` may view ``clip`` by virtue of a shared collection.

    Registered with ``clips.access`` (see ``SharedCollectionsConfig.ready``), so
    ``Clip.is_viewable_by`` consults it for the restricted case. Only reached for
    an authenticated, non-uploader user on a non-PUBLIC clip, so it just answers
    "is this clip in a collection the user owns or is an active member of?".
    """
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


# --- Predicates ---------------------------------------------------------------


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
            cleanup_clip_files_on_commit(clip_id, files)
