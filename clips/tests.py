import os
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

    @mock.patch('clips.views.enqueue_transcode')
    @mock.patch('clips.forms.ClipCreateForm._probe_duration', return_value=42.0)
    def test_ajax_upload_returns_redirect_json(self, _probe, enqueue):
        video = SimpleUploadedFile('clip.mp4', b'\x00\x01fake', content_type='video/mp4')
        resp = self.client.post(
            reverse('clip-create'),
            {'title': 'Ace', 'description': '', 'video_file': video},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['redirect'], reverse('clip-list'))
        enqueue.assert_called_once()

    @mock.patch('clips.forms.ClipCreateForm._probe_duration', return_value=120.0)
    def test_ajax_upload_invalid_returns_error_json(self, _probe):
        video = SimpleUploadedFile('long.mp4', b'\x00\x01fake', content_type='video/mp4')
        resp = self.client.post(
            reverse('clip-create'),
            {'title': 'Long', 'description': '', 'video_file': video},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('video_file', resp.json()['errors'])
        self.assertFalse(Clip.objects.exists())

    @mock.patch('clips.views.enqueue_transcode')
    @mock.patch('clips.forms.ClipCreateForm._probe_duration', return_value=42.0)
    def test_upload_allows_empty_description(self, _probe, enqueue):
        video = SimpleUploadedFile('clip.mp4', b'\x00\x01fake', content_type='video/mp4')
        resp = self.client.post(
            reverse('clip-create'),
            {'title': 'No words needed', 'description': '', 'video_file': video},
        )
        self.assertEqual(resp.status_code, 302)
        clip = Clip.objects.get()
        self.assertEqual(clip.description, '')

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
class ClipBrowseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gamer', password='pw12345!')
        self.other = User.objects.create_user(username='mario', password='pw12345!')
        self.client.force_login(self.user)
        self.ace = Clip.objects.create(
            title='Clutch ace', description='insane battlefield6 moment', uploader=self.user,
            video_file=SimpleUploadedFile('a.mp4', b'x'),
        )
        self.pb = Clip.objects.create(
            title='Speedrun PB', description='', uploader=self.other,
            video_file=SimpleUploadedFile('b.mp4', b'x'),
        )

    def test_search_filters_by_title(self):
        resp = self.client.get(reverse('clip-list'), {'q': 'ace'})
        self.assertContains(resp, 'Clutch ace')
        self.assertNotContains(resp, 'Speedrun PB')

    def test_search_filters_by_description(self):
        resp = self.client.get(reverse('clip-list'), {'q': 'battlefield6'})
        self.assertContains(resp, 'Clutch ace')
        self.assertNotContains(resp, 'Speedrun PB')

    def test_search_filters_by_uploader(self):
        resp = self.client.get(reverse('clip-list'), {'q': 'mario'})
        self.assertContains(resp, 'Speedrun PB')
        self.assertNotContains(resp, 'Clutch ace')

    def test_blank_search_shows_all(self):
        resp = self.client.get(reverse('clip-list'), {'q': '  '})
        self.assertContains(resp, 'Clutch ace')
        self.assertContains(resp, 'Speedrun PB')

    def test_detail_page_renders(self):
        resp = self.client.get(reverse('clip-detail', args=[self.ace.pk]))
        self.assertContains(resp, 'Clutch ace')
        self.assertContains(resp, 'Processing')  # PENDING clip shows status

    def test_status_endpoint_returns_json(self):
        resp = self.client.get(reverse('clip-status', args=[self.ace.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'PENDING', 'thumbnail_url': None})

    def test_detail_404_for_missing_clip(self):
        resp = self.client.get(reverse('clip-detail', args=[99999]))
        self.assertEqual(resp.status_code, 404)


@_TEST_OVERRIDES
class ClipDeleteTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='pw12345!')
        self.intruder = User.objects.create_user(username='intruder', password='pw12345!')
        self.clip = Clip.objects.create(
            title='Mine', description='', uploader=self.owner,
            video_file=SimpleUploadedFile('mine.mp4', b'raw-bytes'),
        )

    def test_owner_can_delete_clip_and_files(self):
        raw_path = self.clip.video_file.path
        self.assertTrue(os.path.exists(raw_path))
        self.client.force_login(self.owner)
        resp = self.client.post(reverse('clip-delete', args=[self.clip.pk]))
        self.assertRedirects(resp, reverse('clip-list'))
        self.assertFalse(Clip.objects.filter(pk=self.clip.pk).exists())
        self.assertFalse(os.path.exists(raw_path))

    def test_non_owner_gets_403(self):
        self.client.force_login(self.intruder)
        resp = self.client.post(reverse('clip-delete', args=[self.clip.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Clip.objects.filter(pk=self.clip.pk).exists())

    def test_anonymous_redirected_to_login(self):
        resp = self.client.post(reverse('clip-delete', args=[self.clip.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])
        self.assertTrue(Clip.objects.filter(pk=self.clip.pk).exists())

    def test_delete_button_only_for_owner(self):
        self.client.force_login(self.intruder)
        resp = self.client.get(reverse('clip-detail', args=[self.clip.pk]))
        self.assertNotContains(resp, 'Delete')
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('clip-detail', args=[self.clip.pk]))
        self.assertContains(resp, 'Delete')


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
        self.assertTrue(clip.thumbnail.name)
        # Raw upload is deleted once the converted file exists.
        self.assertFalse(clip.video_file)

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
