"""Domain operations for the clips app (Flaw #11: service layer).

The transcode task is the worker-side replacement for the old `post_save` signal
(Flaw #1). It runs in a separate `qcluster` process, talks to storage through the
Django storage API (Flaw #3), and records explicit status so failures are visible.
"""
import logging
import os
import tempfile

import ffmpeg
from django.core.files import File
from django_q.tasks import async_task

from .models import Clip

logger = logging.getLogger(__name__)


def enqueue_transcode(clip):
    """Dispatch a clip for asynchronous transcoding. Returns the task id."""
    return async_task('clips.services.transcode_clip', clip.pk)


def transcode_clip(clip_pk):
    """Transcode a clip's raw upload to 720p H.264 and store the result.

    Runs in the django-q2 worker. Downloads the raw input from storage to a local
    temp file (ffmpeg needs a real path), transcodes, then writes the output back
    through the storage API so it works identically on local disk or R2/S3.
    """
    clip = Clip.objects.get(pk=clip_pk)
    clip.status = Clip.Status.PROCESSING
    clip.error_message = ''
    clip.save(update_fields=['status', 'error_message'])

    raw_name = clip.video_file.name
    suffix = os.path.splitext(raw_name)[1] or '.mp4'
    raw_tmp = None
    out_tmp = None
    try:
        # Pull the raw upload down to a local temp file.
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as rt:
            raw_tmp = rt.name
            with clip.video_file.open('rb') as src:
                for chunk in src.chunks():
                    rt.write(chunk)

        out_fd, out_tmp = tempfile.mkstemp(suffix='.mp4')
        os.close(out_fd)

        (
            ffmpeg
            .input(raw_tmp)
            .output(
                out_tmp,
                vcodec='libx264',
                acodec='aac',
                movflags='faststart',
                vf='scale=-2:720',
            )
            .run(overwrite_output=True, quiet=True)
        )

        # Hand the output to the storage backend (local FS or R2) via the API,
        # never by assigning OS paths.
        base = os.path.splitext(os.path.basename(raw_name))[0]
        converted_name = f'converted_{base}.mp4'
        with open(out_tmp, 'rb') as f:
            clip.converted_video_file.save(converted_name, File(f), save=False)
        clip.status = Clip.Status.READY
        clip.save(update_fields=['converted_video_file', 'status'])
        logger.info('Transcoded clip %s -> %s', clip.pk, clip.converted_video_file.name)
        return clip.pk

    except ffmpeg.Error as e:
        stderr = e.stderr.decode('utf-8', 'replace') if e.stderr else str(e)
        logger.error('FFmpeg failed for clip %s: %s', clip.pk, stderr)
        clip.status = Clip.Status.FAILED
        clip.error_message = stderr[-2000:]
        clip.save(update_fields=['status', 'error_message'])
        raise
    except Exception as e:
        logger.exception('Transcode failed for clip %s', clip.pk)
        clip.status = Clip.Status.FAILED
        clip.error_message = str(e)[-2000:]
        clip.save(update_fields=['status', 'error_message'])
        raise
    finally:
        for path in (raw_tmp, out_tmp):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
