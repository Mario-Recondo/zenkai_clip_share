# zenkai_clip_share

## What this is
This is a Django (Python) web app for uploading and viewing “gaming clips”. It uses SQLite for the database in development and transcodes uploads to 720p MP4 in a background worker using `ffmpeg`.

## Prerequisites
- Python 3.10+ (recommended)
- `ffmpeg` installed on your machine and available in your `PATH` (required for video transcoding and thumbnails)

## Setup (Windows / PowerShell)
Done once per machine.

1. Open a terminal in this folder: `zenkai_clip_share`
2. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
4. Create your local `.env` (settings refuse to start without it):
   ```powershell
   Copy-Item .env.example .env
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
   Paste the generated key into `SECRET_KEY=` in `.env`. The example file's dev
   defaults (`DEBUG=True`, `USE_S3=False`) are correct for local work.
5. Verify `ffmpeg` is available:
   ```powershell
   ffmpeg -version
   ```
6. (Recommended) Create an admin user:
   ```powershell
   python manage.py migrate
   python manage.py createsuperuser
   ```

## Run the application
One command starts everything — migrations, the web server, the transcode
worker, and the Tailwind CSS watcher (if the CLI is installed, see below):
```powershell
.\dev.ps1
```
Ctrl+C stops the whole stack. If scripts are blocked by execution policy, run
`powershell -ExecutionPolicy Bypass -File dev.ps1` instead.

<details>
<summary>Running the pieces manually instead</summary>

Each in its own terminal:
```powershell
python manage.py runserver     # web server
python manage.py qcluster      # transcode worker — uploads stay "Processing" forever without it
.\.bin\tailwindcss.exe -i static_src\input.css -o static\css\style.css --watch   # only when editing styles
```
</details>

## Open in your browser
- Home page (redirects to clip list): `http://127.0.0.1:8000/`
- Login: `http://127.0.0.1:8000/login/`
- Admin: `http://127.0.0.1:8000/admin/`

## Frontend build (Tailwind CSS)
The UI is styled with Tailwind CSS v4 via the standalone CLI — no Node.js required. The compiled stylesheet (`static/css/style.css`) is committed, so you only need this when changing styles or templates.

1. Download the standalone CLI into `.bin/` (gitignored):
   ```powershell
   New-Item -ItemType Directory -Force .bin
   Invoke-WebRequest https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-windows-x64.exe -OutFile .bin\tailwindcss.exe
   ```
2. While developing, `dev.ps1` runs the watcher for you (or run the `--watch`
   command above manually).
3. Before committing style changes, build the minified version:
   ```powershell
   .\.bin\tailwindcss.exe -i static_src\input.css -o static\css\style.css --minify
   ```

Design tokens (dark "ink" surfaces, "ember" accent) and form/component styles live in `static_src/input.css`.

## Notes / troubleshooting
- Uploads are transcoded asynchronously by the `qcluster` worker (`clips/services.py`). If a clip is stuck on "Processing", make sure the worker is running (`dev.ps1` starts it); if a clip shows "Failed", ensure `ffmpeg` is installed and on `PATH`.
- Clips transcoded before thumbnails existed can get one via `python manage.py backfill_thumbnails`.
- Uploaded images (profile picture) use Django’s `ImageField`, so `Pillow` is required (installed via requirements.txt).
- Uploads, converted videos, and thumbnails are stored under `media/` in dev (`MEDIA_ROOT`); production uses Cloudflare R2 via `USE_S3=True` in the environment.
