import os
from unittest.mock import patch
import pytest
import app as gallery

ID = '6c09a55d-6f76-4dcc-b2de-da20cd055244'
ROW = dict(image_id=ID, id=ID, object_key='images/dog.webp', title='A sunny walk', caption='A happy dog outdoors.')

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password')
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret')
    monkeypatch.setenv('MEDIA_BASE_URL', 'https://media.example.com/photos/')
    monkeypatch.setenv('SITE_URL', 'https://example.com')
    gallery.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    return gallery.app.test_client()


def test_public_only_queries_curated_table(client):
    with patch.object(gallery, 'query', return_value=[ROW]) as query:
        response = client.get('/')
        assert response.status_code == 200
        assert b'A sunny walk' in response.data
        assert 'gallery_selections' in query.call_args.args[0]
        assert 'saved_images' not in query.call_args.args[0]


def test_admin_requires_auth_and_disallows_indexing(client):
    response = client.get('/admin')
    assert response.status_code == 401
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert response.headers['Cache-Control'] == 'no-store'


def test_csrf_blocks_write(client):
    with patch.object(gallery, 'query') as query:
        response = client.post('/admin/select/' + ID, auth=('admin', 'test-password'), data={'title': 'Test'})
        assert response.status_code == 400
        query.assert_not_called()


def test_publishing_requires_review_and_valid_frame(client):
    with client.session_transaction() as session:
        session['csrf'] = 'token'
    with patch.object(gallery, 'query', return_value=ROW) as query:
        data = {'csrf': 'token', 'title': 'Walk', 'object_key': 'images/dog.webp'}
        assert client.post('/admin/select/' + ID, auth=('admin', 'test-password'), data=data).status_code == 400
        assert query.call_count == 1
        data['reviewed'] = 'yes'
        response = client.post('/admin/select/' + ID, auth=('admin', 'test-password'), data=data)
        assert response.status_code == 302
        assert 'INSERT INTO public.gallery_selections' in query.call_args.args[0]


def test_asset_paths_cannot_escape_configured_directory(client):
    with gallery.app.test_request_context():
        for value in ['../secret', 'https://other.example/x.jpg', '//other.example/x.jpg', 'a/../../x.jpg', 'a\\x.jpg']:
            with pytest.raises(Exception):
                gallery.asset_url(value)


def test_frame_index_extracts_images_without_executing_html():
    parser = gallery.IndexImages()
    parser.feed('<script>alert(1)</script><img src="001.jpg"><a href="002.webp">frame</a><a href="movie.mp4">video</a>')
    assert parser.paths == ['001.jpg', '002.webp']


def test_unselected_photo_is_not_public(client):
    with patch.object(gallery, 'query', return_value=None):
        assert client.get('/photos/' + ID).status_code == 404


def test_sitemap_escapes_titles_and_includes_media(client):
    with patch.object(gallery, 'query', return_value=[dict(ROW, title='Dog & owner')]):
        response = client.get('/sitemap.xml')
        assert response.status_code == 200
        assert b'Dog &amp; owner' in response.data
        assert b'https://media.example.com/photos/images/dog.webp' in response.data
