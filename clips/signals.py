import os

import ffmpeg
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Clip


@receiver(post_save, sender=Clip)
def transcode_video(sender, instance, created, **kwargs):
    # only transcode when a new object is created and has a raw video file
    if created and instance.video_file:
        converted_dir_relative = 'clips/converted'
        converted_dir_path = os.path.join(settings.MEDIA_ROOT, converted_dir_relative)
        os.makedirs(converted_dir_path, exist_ok=True)
        # get the path for the converted video file
        raw_file_path = os.path.join(settings.MEDIA_ROOT, instance.video_file.name)

        # get filename and create output path
        filename = os.path.basename(raw_file_path)
        output_file_path = os.path.join(converted_dir_path, f'converted_{filename}')

        converted_file_relative = os.path.join(converted_dir_relative, f'converted_{filename}')

        # use ffmpeg to transcode video
        try:
            (
                ffmpeg
                .input(raw_file_path)
                .output(output_file_path, vcodec='libx264', acodec='aac', movflags='faststart', vf='scale=-2:720')
                .run(overwrite_output=True, quiet=True)
            )
            # update clip object with the path to converted file
            instance.converted_video_file.name = converted_file_relative
            instance.save(update_fields=['converted_video_file'])

        except ffmpeg.Error as e:
            print(f"FFmpeg error: {e.stderr.decode('utf8')}")
            # log or handle

            # optional, delete original raw upload to save space
            # os.remove(raw_file_path)
