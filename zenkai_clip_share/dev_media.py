"""Range-aware media serving for local development.

Django's `django.views.static.serve` ignores the HTTP Range header, which
breaks video timeline seeking in browsers (they need 206 partial responses
to jump to unbuffered positions). Production serves media from object
storage, which supports ranges natively — this view is only wired up when
DEBUG is on.
"""
import mimetypes
import os
import re

from django.http import Http404, StreamingHttpResponse
from django.utils._os import safe_join
from django.views.static import serve

RANGE_RE = re.compile(r'bytes=(\d*)-(\d*)$')
CHUNK_SIZE = 64 * 1024


def _file_slice(path, start, length):
    with open(path, 'rb') as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def ranged_serve(request, path, document_root=None):
    """Serve a media file, honouring single-part Range requests."""
    match = RANGE_RE.match(request.headers.get('Range', ''))
    if match is None:
        # No (or unsupported multi-part) range: let Django's serve handle it,
        # but advertise that ranges are accepted so players try to seek.
        response = serve(request, path, document_root=document_root)
        response['Accept-Ranges'] = 'bytes'
        return response

    fullpath = safe_join(document_root, path)
    if not os.path.isfile(fullpath):
        raise Http404(f'"{path}" does not exist')
    size = os.path.getsize(fullpath)
    content_type = mimetypes.guess_type(fullpath)[0] or 'application/octet-stream'

    start_s, end_s = match.groups()
    if start_s:
        start = int(start_s)
        end = min(int(end_s), size - 1) if end_s else size - 1
    elif end_s:
        # Suffix range: the last N bytes.
        start = max(size - int(end_s), 0)
        end = size - 1
    else:
        start, end = 0, size - 1

    if start >= size or start > end:
        response = StreamingHttpResponse(iter(()), status=416, content_type=content_type)
        response['Content-Range'] = f'bytes */{size}'
        return response

    length = end - start + 1
    response = StreamingHttpResponse(
        _file_slice(fullpath, start, length), status=206, content_type=content_type
    )
    response['Content-Length'] = str(length)
    response['Content-Range'] = f'bytes {start}-{end}/{size}'
    response['Accept-Ranges'] = 'bytes'
    return response
