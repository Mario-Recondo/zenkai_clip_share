from django.contrib.auth.models import User
from django.db import models


# Create your models here.
class Clip(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"  # row created, transcode not started
        PROCESSING = "PROCESSING", "Processing"  # worker is transcoding
        READY = "READY", "Ready"  # converted file available
        FAILED = "FAILED", "Failed"  # transcode errored (see error_message)

    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    # DateTimeField (not DateField) so "newest first" can break same-day ties (Flaw #6)
    date_uploaded = models.DateTimeField(auto_now_add=True)
    video_file = models.FileField(upload_to="clips/raw_uploads")

    converted_video_file = models.FileField(
        upload_to="clips/converted", null=True, blank=True
    )

    # Poster frame extracted by the transcode worker; cards fall back to a
    # placeholder when missing (extraction failure is non-fatal).
    thumbnail = models.ImageField(upload_to="clips/thumbnails", null=True, blank=True)

    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "Public"  # listed in the public home feed
        UNLISTED = (
            "UNLISTED",
            "Unlisted",
        )  # reachable only via collections / direct link

    # Explicit processing state instead of inferring it from a null file (Flaw #1/#6)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error_message = models.TextField(blank=True, default="")

    uploader = models.ForeignKey(User, on_delete=models.CASCADE)

    # Whether the clip appears in the public home feed. UNLISTED clips live only
    # inside collections (or a direct link); access is gated by is_viewable_by.
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )

    class Meta:
        ordering = ["-date_uploaded"]
        indexes = [
            models.Index(fields=["-date_uploaded"]),
            models.Index(fields=["uploader", "-date_uploaded"]),
            # Keeps the visibility-filtered home feed fast.
            models.Index(fields=["visibility", "-date_uploaded"]),
        ]

    def __str__(self):
        return self.title

    def is_viewable_by(self, user):
        """Whether ``user`` may view this clip (detail page / a listing entry).

        PUBLIC clips are world-viewable. Otherwise the clip is restricted to its
        uploader plus any access granted by feature apps that register a provider
        via ``clips.access`` (e.g. an active collection member). This is the clip
        layer owning its own visibility rule, with collections plugging in rather
        than ``clips`` importing the higher-level feature.
        """
        if self.visibility == self.Visibility.PUBLIC:
            return True
        if not user.is_authenticated:
            return False
        if self.uploader_id == user.id:
            return True
        from clips.access import grants_view

        return grants_view(self, user)
