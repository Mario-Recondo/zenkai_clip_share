"""Views for Collections (build steps 3 + 5 + 6).

Create / list / detail (member-gated) / delete a collection; upload a new clip
into a collection or add an existing own clip; unlink and safe-delete a clip
within a collection; the sharing lifecycle (invite by username, accept /
decline, leave, owner removes a member); and the member's self-service
``allow_owner_delete`` toggle.

All destructive clip actions route through the helpers in ``permissions`` so the
safe-delete contract can never be bypassed. Per-clip routes are link-scoped: they
first prove the (collection, clip) link exists (404 otherwise) before running any
permission check, so a scoped action can't leak into a global destroy.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView

from clips.forms import (
    ALLOWED_EXTENSIONS,
    MAX_DURATION_SECONDS,
    MAX_UPLOAD_SIZE,
    ClipCreateForm,
)
from clips.models import Clip
from clips.services import enqueue_transcode

from .forms import CollectionForm
from .models import Collection, CollectionClip, CollectionMembership
from .permissions import (
    can_delete,
    can_unlink,
    delete_clip_in_collection,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 12

ACTIVE = CollectionMembership.Status.ACTIVE
PENDING = CollectionMembership.Status.PENDING


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _get_active_member_collection(request, pk):
    """Fetch the collection or 404 unless the user is the owner/an active member.

    Returns 404 (not 403) for non-members so a collection's existence isn't
    revealed — it's a members-only workspace.
    """
    collection = get_object_or_404(Collection, pk=pk)
    if not collection.is_active_member(request.user):
        raise Http404("No collection matches the given query.")
    return collection


@login_required
def collection_list(request):
    """Collections the user owns or is an active member of."""
    collection_qs = (
        Collection.objects.filter(
            Q(owner=request.user)
            | Q(memberships__user=request.user, memberships__status=ACTIVE)
        )
        .distinct()
        .select_related("owner")
        .order_by("-created_at")
    )
    page_obj = Paginator(collection_qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "shared_collections/collection_list.html",
        {"collections": page_obj, "page_obj": page_obj, "title": "Collections"},
    )


class CollectionCreateView(LoginRequiredMixin, CreateView):
    model = Collection
    form_class = CollectionForm
    template_name = "shared_collections/collection_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "New collection"
        return context

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("collection-detail", args=[self.object.pk])


@login_required
def collection_detail(request, pk):
    """Clip grid + member list for a collection (active members only)."""
    collection = _get_active_member_collection(request, pk)

    links = collection.collection_clips.select_related(
        "clip", "clip__uploader"
    ).order_by("-added_at")
    page_obj = Paginator(links, PAGE_SIZE).get_page(request.GET.get("page"))

    # Precompute per-clip action permissions: templates can't call helpers that
    # take arguments, and the (collection, clip) link is already proven here.
    clips = []
    for link in page_obj:
        clip = link.clip
        clip.user_can_unlink = can_unlink(collection, request.user, clip)
        clip.user_can_delete = can_delete(collection, request.user, clip)
        clips.append(clip)

    members = collection.memberships.filter(status=ACTIVE).select_related("user")
    is_owner = collection.owner_id == request.user.id
    # Outstanding invites are only the owner's concern.
    pending = (
        collection.memberships.filter(status=PENDING).select_related("user")
        if is_owner
        else CollectionMembership.objects.none()
    )
    # A member's own membership drives the self-service allow_owner_delete toggle
    # (the owner has no membership row).
    my_membership = (
        None
        if is_owner
        else collection.memberships.filter(user=request.user, status=ACTIVE).first()
    )

    return render(
        request,
        "shared_collections/collection_detail.html",
        {
            "collection": collection,
            "clips": clips,
            "page_obj": page_obj,
            "members": members,
            "pending": pending,
            "is_owner": is_owner,
            "my_membership": my_membership,
            "title": collection.name,
        },
    )


class CollectionDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Collection
    template_name = "shared_collections/collection_confirm_delete.html"
    success_url = reverse_lazy("collection-list")
    context_object_name = "collection"

    def test_func(self):
        # Only the owner may delete the collection.
        return self.get_object().owner_id == self.request.user.id

    # Deleting the Collection cascades its CollectionClip rows (unlink-all); the
    # Clip rows are never touched. No safe-delete needed — this only removes links.


@login_required
def collection_upload(request, pk):
    """Upload a brand-new clip directly into a collection (active members only).

    The clip defaults to UNLISTED (collection-only). The "also post to home
    feed" checkbox promotes it to PUBLIC so it also appears on the public feed.
    """
    collection = _get_active_member_collection(request, pk)

    if request.method == "POST":
        form = ClipCreateForm(request.POST, request.FILES)
        if form.is_valid():
            clip = form.save(commit=False)
            clip.uploader = request.user
            # Default UNLISTED (collection-only); opt in to the public home feed.
            clip.visibility = (
                Clip.Visibility.PUBLIC
                if request.POST.get("post_to_home")
                else Clip.Visibility.UNLISTED
            )
            try:
                # Clip row AND its link commit together; a failure rolls both back.
                with transaction.atomic():
                    clip.save()  # writes the DB row AND the file to storage
                    CollectionClip.objects.create(
                        collection=collection, clip=clip, added_by=request.user
                    )
            except Exception:
                # FileField writes are NOT transactional: the bytes survive a DB
                # rollback. Compensate so storage can't leak an orphan, but never
                # let a cleanup failure mask the original error.
                try:
                    if clip.video_file:
                        clip.video_file.delete(save=False)
                except Exception:
                    logger.exception(
                        "collection upload: failed to delete orphaned file "
                        "(storage_key=%s)",
                        getattr(clip.video_file, "name", None),
                    )
                raise
            # Enqueue only after the whole txn commits — never for a rolled-back clip.
            transaction.on_commit(lambda: enqueue_transcode(clip))
            redirect_url = reverse("collection-detail", args=[collection.pk])
            if _is_ajax(request):
                return JsonResponse({"redirect": redirect_url})
            return redirect(redirect_url)
        if _is_ajax(request):
            return JsonResponse({"errors": form.errors}, status=400)
    else:
        form = ClipCreateForm()

    return render(
        request,
        "shared_collections/collection_upload.html",
        {
            "collection": collection,
            "form": form,
            "title": f"Upload to {collection.name}",
            "max_upload_size": MAX_UPLOAD_SIZE,
            "max_duration_seconds": MAX_DURATION_SECONDS,
            "allowed_extensions": ",".join(sorted(ALLOWED_EXTENSIONS)),
        },
    )


@login_required
def collection_add_clip(request, pk):
    """Add an existing clip the user uploaded into the collection (decision #8)."""
    collection = _get_active_member_collection(request, pk)

    # Own clips not already linked to this collection.
    linked_ids = collection.collection_clips.values_list("clip_id", flat=True)
    own_clips = (
        Clip.objects.filter(uploader=request.user)
        .exclude(pk__in=linked_ids)
        .order_by("-date_uploaded")
    )

    if request.method == "POST":
        clip = get_object_or_404(Clip, pk=request.POST.get("clip"))
        # Members may add only their own clips — keeps added_by == uploader.
        if clip.uploader_id != request.user.id:
            raise Http404("No clip matches the given query.")
        # Lock the clip row so a concurrent safe-delete can't race the insert's
        # "still shared?" check (see permissions.delete_clip_in_collection).
        with transaction.atomic():
            Clip.objects.select_for_update().get(pk=clip.pk)
            CollectionClip.objects.get_or_create(
                collection=collection, clip=clip, defaults={"added_by": request.user}
            )
        return redirect("collection-detail", pk=collection.pk)

    page_obj = Paginator(own_clips, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "shared_collections/collection_add_clip.html",
        {
            "collection": collection,
            "clips": page_obj,
            "page_obj": page_obj,
            "title": f"Add a clip to {collection.name}",
        },
    )


def _link_or_404(collection, clip_pk):
    """Prove the (collection, clip) link exists before any per-clip action.

    Link-scoped authorization: without this, an owner with delegated delete (or
    the uploader) could target a clip that lives in a *different* collection and
    turn a scoped action into a global destroy.
    """
    return get_object_or_404(CollectionClip, collection=collection, clip_id=clip_pk)


@login_required
@require_POST
def collection_remove_clip(request, pk, clip_pk):
    """Unlink a clip from the collection (pure unlink; the clip row survives)."""
    collection = _get_active_member_collection(request, pk)
    link = _link_or_404(collection, clip_pk)
    clip = link.clip
    if not can_unlink(collection, request.user, clip):
        raise Http404("No clip matches the given query.")
    CollectionClip.objects.filter(collection=collection, clip=clip).delete()
    return redirect("collection-detail", pk=collection.pk)


@login_required
@require_POST
def collection_delete_clip(request, pk, clip_pk):
    """Safe-delete a clip in the collection: unlink if shared, destroy if sole home."""
    collection = _get_active_member_collection(request, pk)
    link = _link_or_404(collection, clip_pk)
    clip = link.clip
    if not can_delete(collection, request.user, clip):
        raise Http404("No clip matches the given query.")
    delete_clip_in_collection(collection, clip)
    return redirect("collection-detail", pk=collection.pk)


# --- Membership: invite / accept / decline / leave / remove -------------------


def _get_owned_collection(request, pk):
    """Fetch the collection or 404 unless the request user owns it."""
    collection = get_object_or_404(Collection, pk=pk)
    if collection.owner_id != request.user.id:
        raise Http404("No collection matches the given query.")
    return collection


@login_required
@require_POST
def collection_invite(request, pk):
    """Owner invites a user by username, creating a PENDING membership."""
    collection = _get_owned_collection(request, pk)
    username = request.POST.get("username", "").strip()
    invitee = User.objects.filter(username=username).first()

    if invitee is None:
        messages.error(request, f"No user named “{username}”.")
    elif invitee.id == collection.owner_id:
        messages.error(request, "You already own this collection.")
    else:
        _, created = CollectionMembership.objects.get_or_create(
            collection=collection, user=invitee, defaults={"status": PENDING}
        )
        if created:
            messages.success(request, f"Invited {invitee.username}.")
        else:
            messages.error(
                request, f"{invitee.username} is already invited or a member."
            )
    return redirect("collection-detail", pk=collection.pk)


@login_required
@require_POST
def collection_remove_member(request, pk, user_pk):
    """Owner removes a member. Their clips stay (decision #9); the owner then
    auto-gains delete permission over them (handled by ``can_delete``)."""
    collection = _get_owned_collection(request, pk)
    membership = get_object_or_404(
        CollectionMembership, collection=collection, user_id=user_pk
    )
    membership.delete()
    return redirect("collection-detail", pk=collection.pk)


@login_required
@require_POST
def collection_leave(request, pk):
    """An active member leaves. The owner can't leave (they delete instead)."""
    collection = get_object_or_404(Collection, pk=pk)
    if collection.owner_id == request.user.id:
        raise Http404("No collection matches the given query.")
    membership = get_object_or_404(
        CollectionMembership, collection=collection, user=request.user
    )
    membership.delete()
    messages.success(request, f"You left “{collection.name}”.")
    return redirect("collection-list")


@login_required
def my_invites(request):
    """Pending collection invites for the current user; accept or decline."""
    invites = (
        CollectionMembership.objects.filter(user=request.user, status=PENDING)
        .select_related("collection", "collection__owner")
        .order_by("-invited_at")
    )
    return render(
        request,
        "shared_collections/my_invites.html",
        {"invites": invites, "title": "My invites"},
    )


@login_required
@require_POST
def invite_accept(request, pk):
    """Accept a pending invite to collection ``pk`` (status ACTIVE, stamp joined_at)."""
    membership = get_object_or_404(
        CollectionMembership, collection_id=pk, user=request.user, status=PENDING
    )
    membership.status = ACTIVE
    membership.joined_at = timezone.now()
    membership.save(update_fields=["status", "joined_at"])
    return redirect("collection-detail", pk=pk)


@login_required
@require_POST
def invite_decline(request, pk):
    """Decline a pending invite to collection ``pk`` (delete the row)."""
    membership = get_object_or_404(
        CollectionMembership, collection_id=pk, user=request.user, status=PENDING
    )
    membership.delete()
    return redirect("my-invites")


@login_required
@require_POST
def membership_settings(request, pk):
    """A member toggles their own ``allow_owner_delete`` for this collection.

    Self-service only: it acts on the requester's own ACTIVE membership, so the
    owner (who has no membership row) and non-members can't reach it. This opts
    the owner in/out of deleting the member's clips — the active-member branch of
    ``can_delete``; the ex-member auto-permission is independent of this flag.
    """
    membership = get_object_or_404(
        CollectionMembership, collection_id=pk, user=request.user, status=ACTIVE
    )
    membership.allow_owner_delete = bool(request.POST.get("allow_owner_delete"))
    membership.save(update_fields=["allow_owner_delete"])
    return redirect("collection-detail", pk=pk)
