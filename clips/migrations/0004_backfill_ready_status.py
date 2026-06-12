from django.db import migrations


def mark_converted_clips_ready(apps, schema_editor):
    """Clips transcoded before the status field existed were left at the
    PENDING default even though their converted file is ready to play."""
    Clip = apps.get_model('clips', 'Clip')
    Clip.objects.exclude(converted_video_file='').filter(
        status='PENDING'
    ).update(status='READY')


class Migration(migrations.Migration):

    dependencies = [
        ('clips', '0003_alter_clip_options_clip_error_message_clip_status_and_more'),
    ]

    operations = [
        migrations.RunPython(mark_converted_clips_ready, migrations.RunPython.noop),
    ]
