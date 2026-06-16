from django.contrib.auth.models import User
from django.db import models


class Collection(models.Model):
    """A user-owned grouping of clips that can be shared with invited members."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="owned_collections"
    )
    # M2M through an explicit model so each link can carry collection-scoped
    # metadata (who added it, when) without a future schema rewrite + backfill.
    clips = models.ManyToManyField(
        "clips.Clip",
        through="CollectionClip",
        related_name="collections",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def is_active_member(self, user):
        """True if `user` is the owner or an ACTIVE member (owner is always active)."""
        if not user.is_authenticated:
            return False
        if user == self.owner:
            return True
        return self.memberships.filter(
            user=user, status=CollectionMembership.Status.ACTIVE
        ).exists()


class CollectionMembership(models.Model):
    """Invite/accept membership of a user in a collection.

    The PENDING/ACTIVE lifecycle here is the reusable membership primitive
    (watchparty will adopt it). `allow_owner_delete` is collection-specific
    moderation policy and is explicitly NOT part of that reusable lifecycle.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"

    collection = models.ForeignKey(
        Collection, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="collection_memberships"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    # Member opts the owner into deleting their clips in this collection.
    # Collection-specific policy — do not migrate into the shared membership model.
    allow_owner_delete = models.BooleanField(default=False)
    invited_at = models.DateTimeField(auto_now_add=True)
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("collection", "user")

    def __str__(self):
        return f"{self.user} in {self.collection} ({self.status})"


class CollectionClip(models.Model):
    """Through model linking a Clip into a Collection.

    v1 enforces ``added_by == clip.uploader`` (members add only their own clips),
    but recording the link explicitly keeps the door open for per-collection
    ordering / moderation / roles without a migration + backfill later.
    """

    collection = models.ForeignKey(
        Collection, on_delete=models.CASCADE, related_name="collection_clips"
    )
    clip = models.ForeignKey(
        "clips.Clip", on_delete=models.CASCADE, related_name="collection_clips"
    )
    added_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="added_collection_clips"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("collection", "clip")
        ordering = ["-added_at"]

    def __str__(self):
        return f"{self.clip} in {self.collection}"
