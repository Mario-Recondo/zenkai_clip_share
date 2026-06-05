import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Clip

# Production security settings turn on when DEBUG=False (which is the case under
# tests); disable the HTTPS redirect so the test client's http requests aren't 301'd.
# Keep media writes out of the real media/ tree.
_TEST_OVERRIDES = override_settings(
    SECURE_SSL_REDIRECT=False,
    MEDIA_ROOT=tempfile.mkdtemp(prefix='zenkai-test-media-'),
)


@_TEST_OVERRIDES
class ClipUploadFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gamer', password='pw12345!')
        self.client.force_login(self.user)

    @mock.patch('clips.views.enqueue_transcode')
    @mock.patch('clips.forms.ClipCreateForm._probe_duration', return_value=42.0)
    def test_upload_creates_pending_clip_and_enqueues(self, _probe, enqueue):
        video = SimpleUploadedFile('clip.mp4', b'\x00\x01fake', content_type='video/mp4')
        resp = self.client.post(
            reverse('clip-create'),
            {'title': 'Ace', 'description': 'clutch', 'video_file': video},
        )
        self.assertEqual(resp.status_code, 302)
        clip = Clip.objects.get()
        self.assertEqual(clip.status, Clip.Status.PENDING)
        self.assertEqual(clip.uploader, self.user)
        enqueue.assert_called_once_with(clip)

    @mock.patch('clips.forms.ClipCreateForm._probe_duration', return_value=120.0)
    def test_upload_rejected_when_too_long(self, _probe):
        video = SimpleUploadedFile('long.mp4', b'\x00\x01fake', content_type='video/mp4')
        resp = self.client.post(
            reverse('clip-create'),
            {'title': 'Long', 'description': 'too long', 'video_file': video},
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertContains(resp, 'too long')
        self.assertFalse(Clip.objects.exists())

    @mock.patch('clips.forms.ClipCreateForm._probe_duration', return_value=10.0)
    def test_upload_rejected_for_bad_extension(self, _probe):
        bad = SimpleUploadedFile('clip.exe', b'MZ', content_type='application/octet-stream')
        resp = self.client.post(
            reverse('clip-create'),
            {'title': 'Bad', 'description': 'nope', 'video_file': bad},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Clip.objects.exists())


@_TEST_OVERRIDES
class TranscodeTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gamer', password='pw12345!')

    def _make_clip(self):
        return Clip.objects.create(
            title='t', description='d', uploader=self.user,
            video_file=SimpleUploadedFile('raw.mp4', b'\x00\x01raw'),
        )

    @mock.patch('clips.services.ffmpeg')
    def test_transcode_marks_ready(self, fake_ffmpeg):
        from clips import services

        clip = self._make_clip()

        # Pretend ffmpeg wrote a converted file at the temp output path.
        def fake_run(*a, **k):
            out = fake_ffmpeg.input.return_value.output.call_args[0][0]
            with open(out, 'wb') as f:
                f.write(b'converted-bytes')
        fake_ffmpeg.input.return_value.output.return_value.run.side_effect = fake_run

        services.transcode_clip(clip.pk)

        clip.refresh_from_db()
        self.assertEqual(clip.status, Clip.Status.READY)
        self.assertTrue(clip.converted_video_file.name)

    @mock.patch('clips.services.ffmpeg')
    def test_transcode_marks_failed_on_error(self, fake_ffmpeg):
        from clips import services

        clip = self._make_clip()
        # Distinct class so RuntimeError falls through to the generic handler,
        # not the ffmpeg.Error branch.
        fake_ffmpeg.Error = type('FFmpegError', (Exception,), {})
        fake_ffmpeg.input.return_value.output.return_value.run.side_effect = RuntimeError('boom')

        with self.assertRaises(RuntimeError):
            services.transcode_clip(clip.pk)

        clip.refresh_from_db()
        self.assertEqual(clip.status, Clip.Status.FAILED)
        self.assertIn('boom', clip.error_message)
