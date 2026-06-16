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
    # inside collections (or a direct link); access is gated by can_view (later step).
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
