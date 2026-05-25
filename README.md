# zenkai_clip_share

## What this is
This is a Django (Python) web app for uploading and viewing “gaming clips”. It uses SQLite for the database and performs video transcoding on upload using `ffmpeg`.

## Prerequisites
- Python 3.10+ (recommended)
- `ffmpeg` installed on your machine and available in your `PATH` (required for video transcoding)

## Setup (Windows / PowerShell)
1. Open a terminal in this folder: `zenkai_clip_share`
2. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```powershell
   python -m pip install --upgrade pip
   pip install "Django>=5.2,<6" pillow ffmpeg-python
   ```
4. Verify `ffmpeg` is available:
   ```powershell
   ffmpeg -version
   ```

## Run the application
1. Apply database migrations:
   ```powershell
   python manage.py migrate
   ```
2. (Recommended) Create an admin user:
   ```powershell
   python manage.py createsuperuser
   ```
3. Start the dev server:
   ```powershell
   python manage.py runserver
   ```

## Open in your browser
- Home page (redirects to clip list): `http://127.0.0.1:8000/`
- Login: `http://127.0.0.1:8000/login/`
- Admin: `http://127.0.0.1:8000/admin/`

## Notes / troubleshooting
- Video transcoding happens when a new `Clip` is saved (see `clips/signals.py`). If transcoding fails, ensure the `ffmpeg` binary is installed and on `PATH`.
- Uploaded images (profile picture) use Django’s `ImageField`, so `pillow` is required.
- Uploads and converted videos are stored under `media/` (configured by `MEDIA_ROOT` in `zenkai_clip_share/settings.py`).

