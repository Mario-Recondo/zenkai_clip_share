"""Domain operations for the clips app (Flaw #11: service layer).

The transcode task is the worker-side replacement for the old `post_save` signal
(Flaw #1). It runs in a separate `qcluster` process, talks to storage through the
Django storage API (Flaw #3), and records explicit status so failures are visible.
"""

import contextlib
import logging
import os
import tempfile
from datetime import timedelta

import ffmpeg
from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from django_q.tasks import async_task

from .models import Clip

logger = logging.getLogger(__name__)

# Where clip media lives in storage (mirrors the FileField upload_to paths).
CLIP_MEDIA_PREFIXES = ("clips/raw_uploads", "clips/converted", "clips/thumbnails")


def enqueue_transcode(clip):
    """Dispatch a clip for asynchronous transcoding. Returns the task id."""
    return async_task("clips.services.transcode_clip", clip.pk)


# --- Destructive deletion -----------------------------------------------------
#
# These live on the clips side (the domain layer) so destroying a clip never
# requires importing a higher-level feature. ``shared_collections`` reuses
# ``cleanup_clip_files_on_commit`` for its safe in-collection delete.


def cleanup_clip_files_on_commit(clip_id, files):
    """Queue best-effort storage cleanup to run AFTER the outermost commit.

    Never raises: the DB row is already gone, so a storage hiccup may orphan
    files (the reaper job reclaims them) but must not resurrect the clip or mask
    the caller's flow.
    """

    def cleanup():
        for f in files:
            if not f:
                continue
            try:
                f.delete(save=False)
            except Exception:
                logger.exception(
                    "orphaned media after clip delete (clip_id=%s)", clip_id
                )

    transaction.on_commit(cleanup)


def destroy_clip(clip):
    """Fully destroy a clip (row + files), cascading its collection links.

    The ONLY full-destroy entry point, so the safe-delete contract can't be
    silently bypassed. Locks the clip row and queues file cleanup via
    ``transaction.on_commit`` so a surrounding rollback can never leave bytes
    deleted while the row survives. Requires a row-locking backend (PostgreSQL).
    """
    with transaction.atomic():
        clip = Clip.objects.select_for_update().get(pk=clip.pk)
        files = [clip.video_file, clip.converted_video_file, clip.thumbnail]
        clip_id = clip.pk
        clip.delete()  # cascades CollectionClip rows
        cleanup_clip_files_on_commit(clip_id, files)


def _extract_frame(video_path, out_path):
    """Write a single poster frame as JPEG. Tries 1s in first (frame 0 is
    often black), falling back to the very first frame for sub-second clips."""
    for seek in (1.0, 0.0):
        try:
            (
                ffmpeg.input(video_path, ss=seek)
                .output(out_path, vframes=1, vf="scale=640:-2", **{"qscale:v": 3})
                .run(overwrite_output=True, quiet=True)
            )
            if os.path.getsize(out_path) > 0:
                return True
        except (ffmpeg.Error, OSError):
            continue
    return False


def generate_thumbnail(clip, local_video_path):
    """Extract a poster frame from a local video file onto clip.thumbnail.

    Does not save the model; the caller decides which fields to persist.
    Returns True on success. Failure is non-fatal by design — a card without
    a thumbnail renders a placeholder.
    """
    thumb_fd, thumb_tmp = tempfile.mkstemp(suffix=".jpg")
    os.close(thumb_fd)
    try:
        if not _extract_frame(local_video_path, thumb_tmp):
            logger.warning("Thumbnail extraction failed for clip %s", clip.pk)
            return False
        base = os.path.splitext(os.path.basename(clip.video_file.name))[0]
        with open(thumb_tmp, "rb") as f:
            clip.thumbnail.save(f"thumb_{base}.jpg", File(f), save=False)
        return True
    finally:
        if os.path.exists(thumb_tmp):
            with contextlib.suppress(OSError):
                os.remove(thumb_tmp)


def transcode_clip(clip_pk):
    """Transcode a clip's raw upload to 720p H.264 and store the result.

    Runs in the django-q2 worker. Downloads the raw input from storage to a local
    temp file (ffmpeg needs a real path), transcodes, then writes the output back
    through the storage API so it works identically on local disk or R2/S3.
    """
    clip = Clip.objects.get(pk=clip_pk)
    clip.status = Clip.Status.PROCESSING
    clip.error_message = ""
    clip.save(update_fields=["status", "error_message"])

    raw_name = clip.video_file.name
    suffix = os.path.splitext(raw_name)[1] or ".mp4"
    raw_tmp = None
    out_tmp = None
    try:
        # Pull the raw upload down to a local temp file.
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as rt:
            raw_tmp = rt.name
            with clip.video_file.open("rb") as src:
                for chunk in src.chunks():
                    rt.write(chunk)

        out_fd, out_tmp = tempfile.mkstemp(suffix=".mp4")
        os.close(out_fd)

        (
            ffmpeg.input(raw_tmp)
            .output(
                out_tmp,
                vcodec="libx264",
                acodec="aac",
                movflags="faststart",
                vf="scale=-2:720",
            )
            .run(overwrite_output=True, quiet=True)
        )

        # Hand the output to the storage backend (local FS or R2) via the API,
        # never by assigning OS paths.
        base = os.path.splitext(os.path.basename(raw_name))[0]
        converted_name = f"converted_{base}.mp4"
        with open(out_tmp, "rb") as f:
            clip.converted_video_file.save(converted_name, File(f), save=False)
        generate_thumbnail(clip, out_tmp)
        # Durably record the success BEFORE touching storage destructively: once
        # this commits, the clip is READY and plays from the converted file.
        clip.status = Clip.Status.READY
        clip.save(update_fields=["converted_video_file", "thumbnail", "status"])
        logger.info("Transcoded clip %s -> %s", clip.pk, clip.converted_video_file.name)

        # The converted file is now the source of truth, so drop the raw upload
        # (it would otherwise double storage use and sit reachable on the public
        # R2 domain). This is best-effort: the clip is already READY, so a
        # failure here is a storage leak at worst — never re-raise or downgrade
        # the clip, which would also wrongly delete the raw of FAILED clips and
        # block re-enqueuing.
        try:
            clip.video_file.delete(save=False)
            clip.save(update_fields=["video_file"])
        except Exception:
            logger.warning(
                "Could not delete raw upload for clip %s", clip.pk, exc_info=True
            )
        return clip.pk

    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8", "replace") if e.stderr else str(e)
        logger.error("FFmpeg failed for clip %s: %s", clip.pk, stderr)
        clip.status = Clip.Status.FAILED
        clip.error_message = stderr[-2000:]
        clip.save(update_fields=["status", "error_message"])
        raise
    except Exception as e:
        logger.exception("Transcode failed for clip %s", clip.pk)
        clip.status = Clip.Status.FAILED
        clip.error_message = str(e)[-2000:]
        clip.save(update_fields=["status", "error_message"])
        raise
    finally:
        for path in (raw_tmp, out_tmp):
            if path and os.path.exists(path):
                with contextlib.suppress(OSError):
                    os.remove(path)


def _iter_storage_files(storage, prefix):
    """Yield every stored object path under ``prefix`` (recursively).

    Uses the storage API so it works identically on local disk and S3/R2.
    """
    try:
        dirs, files = storage.listdir(prefix)
    except FileNotFoundError:
        return  # prefix doesn't exist yet (nothing uploaded) — nothing to walk
    for name in files:
        yield f"{prefix}/{name}"
    for subdir in dirs:
        yield from _iter_storage_files(storage, f"{prefix}/{subdir}")


def reap_orphan_media(min_age_hours=None):
    """Delete stored clip media objects that no live ``Clip`` row references.

    The two delete paths (``delete_clip_in_collection`` / ``destroy_clip`` and
    the upload-compensation in the collection upload view) remove the DB row
    first and clean files up best-effort, so a storage hiccup can orphan media.
    This scheduled reconciliation sweeps those leaks (plus any pre-existing
    ones): it walks the clip media prefixes and deletes objects that are both
    (a) unreferenced by any Clip FileField and (b) older than the age threshold,
    so an in-flight upload — file written just before its row commits — is never
    reaped. Returns the number of objects deleted.
    """
    if min_age_hours is None:
        min_age_hours = getattr(settings, "ORPHAN_MEDIA_MIN_AGE_HOURS", 6)

    storage = default_storage
    # Every file name referenced by a live Clip, across all three FileFields.
    referenced = set()
    for names in Clip.objects.values_list(
        "video_file", "converted_video_file", "thumbnail"
    ):
        referenced.update(name for name in names if name)

    cutoff = timezone.now() - timedelta(hours=min_age_hours)
    deleted = 0
    for prefix in CLIP_MEDIA_PREFIXES:
        for name in _iter_storage_files(storage, prefix):
            if name in referenced:
                continue
            try:
                modified = storage.get_modified_time(name)
            except (NotImplementedError, OSError):
                continue  # can't determine age — leave it for a later pass
            if timezone.is_naive(modified):
                modified = timezone.make_aware(modified)
            if modified > cutoff:
                continue  # too new — could be an upload mid-commit
            try:
                storage.delete(name)
                deleted += 1
                logger.info("orphan reaper: deleted unreferenced media %s", name)
            except Exception:
                logger.exception("orphan reaper: failed to delete %s", name)

    logger.info("orphan reaper: removed %s orphaned media object(s)", deleted)
    return deleted
