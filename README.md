# Playful Paws — Flask image gallery

A curated gallery for nonsexual dog-and-owner photography. Includes a private image picker, captions, responsive photo cards, individual photo pages, canonical links, Open Graph image metadata, and an image sitemap. Only manually selected photos appear publicly.

## Database discovery

The supplied Neon project `neon-yellow-lamp` (`shy-dew-45386581`), default branch `br-square-star-ahqsz59o`, database `neondb`, currently exposes `public.saved_images` with `id`, `object_key`, `title`, dimensions, and source metadata. **There is no `frame_path` column in that table.** The application uses existing saved images until the correct source/column is supplied. No live database migration or publication was performed during setup.

## Start locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env, then export its values into your shell or use your host's environment settings.
# Flask loads .env automatically only when python-dotenv is installed.
flask --app app init-gallery
flask --app app run
```

For local HTTP set `COOKIE_SECURE=false`. Generate separate random values for `ADMIN_PASSWORD` and `FLASK_SECRET_KEY`, for example with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Keep the session secret stable across app restarts and instances. Use HTTPS for admin access in production.

`init-gallery` creates only `public.gallery_selections`; it does not modify the source table. Run schema changes against a test branch first. Set `DATABASE_URL` to a direct connection for schema setup, then use the pooled URL for normal app traffic.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection to the existing source database |
| `MEDIA_BASE_URL` | Public HTTPS base directory containing `object_key` paths, e.g. `https://cdn.example.com/photos/` |
| `SITE_URL` | Canonical public HTTPS site origin |
| `SITE_NAME` | Display name; defaults to Playful Paws |
| `ADMIN_USERNAME` | Defaults to admin |
| `ADMIN_PASSWORD` | Private editor password; no default |
| `FLASK_SECRET_KEY` | Stable random session signing key |
| `COOKIE_SECURE` | Defaults to true; false for local HTTP only |
| `FRAME_PATH_COLUMN` | Optional existing column on `public.saved_images` containing frame folder paths |

The editor is `/admin`. Select a source image, choose its frame, enter a title/caption, and confirm publication review. A separate remove button unpublishes the selection without deleting source data.

## Frame folders

When the actual database has a suitable frame column, set `FRAME_PATH_COLUMN=frame_path`. A value like `frames/6c09a55d-6f76-4dcc-b2de-da20cd055244-0d3fb83a6ed6469087fa967704fc501b/` resolves to `MEDIA_BASE_URL + frame_path + index.html`.

The server parses `<img src>` and image `<a href>` attributes from the index. It does not embed or execute the stored HTML. Relative JPG, JPEG, PNG, WebP, and AVIF files inside that folder appear as selectable frames. Requests have time and size limits, redirects are rejected, and selection is limited to 500 frames. JavaScript-generated indexes require a separate manifest adapter.

Media must be publicly reachable under stable URLs for this version. Private Neon storage needs an authenticated storage adapter or a CDN setup; do not use expiring presigned URLs as `MEDIA_BASE_URL`. No storage credentials belong in browser code.

## Hosting

Run `gunicorn app:app` on a Python host. For Vercel, import this repository and configure the environment variables. The Flask entry point is `app.py`; `vercel.json` routes requests to it. Run the schema setup separately before serving gallery pages. Hosting has not been provisioned or deployed by this change.

`/health` checks application startup and whether a database URL is configured; it does not test connectivity. `/sitemap.xml` includes only selected photos and stable image URLs. This starter caps sitemap output at 1,000 photos and returns an explicit error above that limit; add sitemap shards before exceeding it. Metadata helps discovery but does not guarantee indexing or rankings. Automated content classification and rate limiting are not included; the editor performs publication review.

## Tests

```bash
pip install pytest
python -m pytest -q
```

Tests cover public selection isolation, authentication, CSRF, required review, asset path validation, HTML index parsing, missing photo handling, and sitemap escaping. They mock database access; live database and storage integration still require the correct frame source and public media origin.
