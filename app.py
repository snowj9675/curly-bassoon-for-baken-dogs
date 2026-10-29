import hmac
import os
import secrets
from functools import wraps
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from uuid import UUID
from xml.sax.saxutils import escape

import click
import psycopg
import requests
from flask import Flask, abort, redirect, render_template, request, session, url_for, Response
from psycopg import sql
from psycopg.rows import dict_row

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'true').lower() == 'true', MAX_CONTENT_LENGTH=16384)


def query(statement, params=(), one=False):
    dsn = os.getenv('DATABASE_URL')
    if not dsn:
        abort(503, 'Set DATABASE_URL to connect the gallery.')
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as conn:
        conn.execute("SET statement_timeout = '10000'")
        result = conn.execute(statement, params)
        if result.description:
            return result.fetchone() if one else result.fetchall()


def source_image(image_id):
    try:
        UUID(image_id)
    except ValueError:
        abort(404)
    column = os.getenv('FRAME_PATH_COLUMN', '').strip()
    frame = sql.Identifier(column) if column else sql.SQL('NULL::text')
    row = query(sql.SQL('SELECT id, title, object_key, width, height, {} AS frame_path FROM public.saved_images WHERE id = %s').format(frame), (image_id,), one=True)
    if not row:
        abort(404)
    return row


def asset_url(key):
    base = os.getenv('MEDIA_BASE_URL', '').rstrip('/') + '/'
    if not base.startswith('https://'):
        abort(503, 'Set MEDIA_BASE_URL to the public HTTPS media directory.')
    # Only object paths within the configured media directory are accepted.
    if not key or '%' in key or key.startswith(('/', '\\')) or '\\' in key or any(p in ('.', '..') for p in key.split('/')):
        abort(400, 'Invalid media key')
    url = urljoin(base, key)
    if not url.startswith(base) or urlsplit(url).query or urlsplit(url).fragment:
        abort(400, 'Invalid media key')
    return url


class IndexImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get('src') if tag == 'img' else attrs.get('href') if tag == 'a' else None
        if value and urlsplit(value).path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.avif')):
            self.paths.append(value)


def candidates(row):
    if not row.get('frame_path'):
        return [row['object_key']]
    prefix = row['frame_path'].rstrip('/') + '/'
    index_url = asset_url(prefix + 'index.html')
    try:
        with requests.get(index_url, timeout=(5, 15), allow_redirects=False, stream=True) as response:
            response.raise_for_status()
            if response.status_code != 200:
                abort(502, 'Frame index must return HTTP 200.')
            data = bytearray()
            for chunk in response.iter_content(8192):
                data.extend(chunk)
                if len(data) > 2_000_000:
                    abort(502, 'Frame index is too large.')
    except requests.RequestException:
        abort(502, 'Could not read the frame index.')
    parser = IndexImages()
    parser.feed(data.decode('utf-8', errors='replace'))
    found = []
    for path in parser.paths:
        resolved = urljoin(index_url, path)
        base = asset_url(prefix)
        if resolved.startswith(base) and not urlsplit(resolved).query and not urlsplit(resolved).fragment:
            key = prefix + resolved[len(base):]
            asset_url(key)
            if key not in found:
                found.append(key)
    return found[:500]


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        password = os.getenv('ADMIN_PASSWORD', '')
        if not password or not os.getenv('FLASK_SECRET_KEY'):
            abort(503, 'Configure ADMIN_PASSWORD and FLASK_SECRET_KEY.')
        auth = request.authorization
        if not auth or not hmac.compare_digest(auth.username or '', os.getenv('ADMIN_USERNAME', 'admin')) or not hmac.compare_digest(auth.password or '', password):
            return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Gallery editor"'})
        session.setdefault('csrf', secrets.token_hex(32))
        if request.method == 'POST' and not hmac.compare_digest(request.form.get('csrf', ''), session['csrf']):
            abort(400, 'Invalid form token')
        return fn(*args, **kwargs)
    return wrapped


@app.context_processor
def context():
    return dict(asset_url=asset_url, site_name=os.getenv('SITE_NAME', 'Playful Paws'))


def public_url(path):
    base = os.getenv('SITE_URL', '').rstrip('/')
    if not base.startswith('https://'):
        return None
    return base + path


@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' https:; style-src 'self'; script-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    if request.path.startswith('/admin'):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
def home():
    page = max(1, request.args.get('page', 1, type=int))
    rows = query('SELECT * FROM public.gallery_selections ORDER BY updated_at DESC, image_id LIMIT 25 OFFSET %s', ((page - 1) * 24,))
    return render_template('home.html', rows=rows[:24], page=page, more=len(rows) > 24, canonical=public_url('/' if page == 1 else f'/?page={page}'))


@app.get('/photos/<image_id>')
def photo(image_id):
    try:
        UUID(image_id)
    except ValueError:
        abort(404)
    row = query('SELECT * FROM public.gallery_selections WHERE image_id = %s', (image_id,), one=True)
    if not row:
        abort(404)
    return render_template('photo.html', row=row, canonical=public_url(url_for('photo', image_id=image_id)))


@app.get('/admin')
@admin_required
def admin():
    page = max(1, request.args.get('page', 1, type=int))
    rows = query('SELECT s.id, s.title, s.object_key, g.image_id AS selected FROM public.saved_images s LEFT JOIN public.gallery_selections g ON g.image_id = s.id ORDER BY s.created_at DESC, s.id LIMIT 25 OFFSET %s', ((page - 1) * 24,))
    return render_template('admin.html', rows=rows[:24], page=page, more=len(rows) > 24)


@app.route('/admin/select/<image_id>', methods=['GET', 'POST'])
@admin_required
def select(image_id):
    row = source_image(image_id)
    keys = candidates(row)
    if request.method == 'POST':
        if request.form.get('action') == 'remove':
            query('DELETE FROM public.gallery_selections WHERE image_id = %s', (image_id,))
            return redirect(url_for('admin'))
        key = request.form.get('object_key', '')
        title = request.form.get('title', '').strip()
        caption = request.form.get('caption', '').strip()
        if key not in keys or not title or len(title) > 160 or len(caption) > 2000 or request.form.get('reviewed') != 'yes':
            abort(400, 'Select a frame, add a title, and confirm the publication review.')
        query('''INSERT INTO public.gallery_selections (image_id, object_key, title, caption)
                 VALUES (%s, %s, %s, %s) ON CONFLICT (image_id) DO UPDATE
                 SET object_key=EXCLUDED.object_key, title=EXCLUDED.title, caption=EXCLUDED.caption, updated_at=now()''', (image_id, key, title, caption))
        return redirect(url_for('photo', image_id=image_id))
    selected = query('SELECT * FROM public.gallery_selections WHERE image_id=%s', (image_id,), one=True)
    return render_template('select.html', row=row, keys=keys, selected=selected)


@app.get('/robots.txt')
def robots():
    sitemap = public_url('/sitemap.xml')
    return Response('User-agent: *\nDisallow: /admin\n' + (f'Sitemap: {sitemap}\n' if sitemap else ''), mimetype='text/plain')


@app.get('/sitemap.xml')
def sitemap():
    if not public_url('/'):
        abort(503, 'Set SITE_URL before generating the sitemap.')
    # Starter limit; no unselected source records are exposed.
    rows = query('SELECT image_id, object_key, title FROM public.gallery_selections ORDER BY image_id LIMIT 1001')
    if len(rows) > 1000:
        abort(503, 'Sitemap capacity reached; add shards before publishing additional photos.')
    entries = ['<url><loc>' + escape(public_url('/')) + '</loc></url>']
    for row in rows:
        entries.append('<url><loc>' + escape(public_url(url_for('photo', image_id=row['image_id']))) + '</loc><image:image><image:loc>' + escape(asset_url(row['object_key'])) + '</image:loc><image:title>' + escape(row['title']) + '</image:title></image:image></url>')
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">' + ''.join(entries) + '</urlset>', mimetype='application/xml')


@app.errorhandler(psycopg.Error)
def database_error(error):
    app.logger.error('Database request failed: %s', type(error).__name__)
    return 'Gallery database unavailable. Check the connection and run init-gallery before serving requests.', 503


@app.get('/health')
def health():
    return {'status': 'ok', 'database_configured': bool(os.getenv('DATABASE_URL'))}


@app.cli.command('init-gallery')
def init_gallery():
    """Create the separate curation table; leave source records untouched."""
    with open(os.path.join(app.root_path, 'schema.sql')) as handle:
        query(handle.read())
    click.echo('Gallery selection table is ready.')


if __name__ == '__main__':
    app.run()
