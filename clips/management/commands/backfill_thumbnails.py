"""Generate poster-frame thumbnails for READY clips that predate the
thumbnail pipeline. Safe to re-run; clips that already have one are skipped."""
import os
import tempfile

from django.core.management.base import BaseCommand
from django.db.models import Q

from clips.models import Clip
from clips.services import generate_thumbnail


class Command(BaseCommand):
    help = 'Extract thumbnails for READY clips that do not have one yet.'

    def handle(self, *args, **options):
        clips = (
            Clip.objects.filter(status=Clip.Status.READY)
            .filter(Q(thumbnail='') | Q(thumbnail__isnull=True))
            .exclude(converted_video_file='')
        )
        done = failed = 0
        for clip in clips:
            # Pull the converted file down via the storage API (works for both
            # local disk and R2) since ffmpeg needs a real path.
            local_tmp = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                    local_tmp = tmp.name
                    with clip.converted_video_file.open('rb') as src:
                        for chunk in src.chunks():
                            tmp.write(chunk)
                if generate_thumbnail(clip, local_tmp):
                    clip.save(update_fields=['thumbnail'])
                    done += 1
                    self.stdout.write(f'clip {clip.pk}: {clip.thumbnail.name}')
                else:
                    failed += 1
                    self.stderr.write(f'clip {clip.pk}: extraction failed')
            finally:
                if local_tmp and os.path.exists(local_tmp):
                    try:
                        os.remove(local_tmp)
                    except OSError:
                        pass
        self.stdout.write(self.style.SUCCESS(f'{done} thumbnail(s) generated, {failed} failed.'))
