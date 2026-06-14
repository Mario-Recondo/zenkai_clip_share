import contextlib
import os
import tempfile

import ffmpeg
from django import forms

from .models import Clip

# Upload limits (Flaw #5). The 90s cap is the product rule; the size cap is a
# cheap pre-filter against disk-exhaustion before we bother probing the file.
# 96 MB keeps uploads under Cloudflare's free-plan 100 MB request-body limit —
# anything larger is rejected with a 413 at the edge before Django sees it.
MAX_UPLOAD_SIZE = 96 * 1024 * 1024  # 96 MB
MAX_DURATION_SECONDS = 90
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
    "video/x-msvideo",
}


class ClipCreateForm(forms.ModelForm):
    class Meta:
        model = Clip
        fields = ["title", "description", "video_file"]

    def clean_video_file(self):
        f = self.cleaned_data["video_file"]

        # Size
        if f.size > MAX_UPLOAD_SIZE:
            raise forms.ValidationError(
                f"File is too large (max {MAX_UPLOAD_SIZE // (1024 * 1024)} MB)."
            )

        # Extension allow-list
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError(
                f'Unsupported file type "{ext}". '
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            )

        # Browser-reported content type (advisory; ffprobe below is authoritative)
        content_type = getattr(f, "content_type", "") or ""
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            raise forms.ValidationError(f'Unsupported content type "{content_type}".')

        # Probe the actual media: this both confirms it is a real video (magic-byte
        # equivalent — a renamed non-video fails here) and enforces the 90s cap.
        duration = self._probe_duration(f, ext)
        if duration is None:
            raise forms.ValidationError("This file could not be read as a video.")
        if duration > MAX_DURATION_SECONDS + 0.5:
            raise forms.ValidationError(
                f"Clip is too long ({duration:.0f}s). "
                f"The maximum length is {MAX_DURATION_SECONDS} seconds."
            )

        return f

    @staticmethod
    def _probe_duration(f, ext):
        """Return the upload's duration in seconds, or None if it isn't a video.

        Writes the upload to a temp file because ffprobe needs a real path. Only
        reads metadata — this is fast and is not a transcode.
        """
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = tmp.name
                for chunk in f.chunks():
                    tmp.write(chunk)
            meta = ffmpeg.probe(tmp_path)
            return float(meta["format"]["duration"])
        except (ffmpeg.Error, KeyError, ValueError, TypeError):
            return None
        finally:
            f.seek(0)  # rewind so the view can still save the full upload
            if tmp_path and os.path.exists(tmp_path):
                with contextlib.suppress(OSError):
                    os.remove(tmp_path)
