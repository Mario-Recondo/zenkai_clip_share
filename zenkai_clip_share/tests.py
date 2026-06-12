import os
import tempfile

from django.test import RequestFactory, SimpleTestCase

from .dev_media import ranged_serve

CONTENT = b'0123456789abcdef'  # 16 bytes


class RangedServeTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = tempfile.mkdtemp(prefix='zenkai-test-range-')
        with open(os.path.join(cls.root, 'clip.mp4'), 'wb') as f:
            f.write(CONTENT)
        cls.factory = RequestFactory()

    def _get(self, range_header=None):
        headers = {'HTTP_RANGE': range_header} if range_header else {}
        request = self.factory.get('/media/clip.mp4', **headers)
        return ranged_serve(request, 'clip.mp4', document_root=self.root)

    def test_full_file_without_range(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Accept-Ranges'], 'bytes')

    def test_open_ended_range(self):
        resp = self._get('bytes=4-')
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(b''.join(resp.streaming_content), CONTENT[4:])
        self.assertEqual(resp['Content-Range'], f'bytes 4-15/{len(CONTENT)}')

    def test_bounded_range(self):
        resp = self._get('bytes=2-5')
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(b''.join(resp.streaming_content), CONTENT[2:6])
        self.assertEqual(resp['Content-Length'], '4')

    def test_suffix_range(self):
        resp = self._get('bytes=-4')
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(b''.join(resp.streaming_content), CONTENT[-4:])

    def test_unsatisfiable_range(self):
        resp = self._get('bytes=99-')
        self.assertEqual(resp.status_code, 416)
        self.assertEqual(resp['Content-Range'], f'bytes */{len(CONTENT)}')
