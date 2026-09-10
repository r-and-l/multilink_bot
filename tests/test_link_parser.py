import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.constants import SERVICES
from src.link_parser import LinkParser, MTSParser, SpotifyParser, YandexParser, parse_link

SPOTIFY_URL = 'https://open.spotify.com/track/123'
YANDEX_ALBUM_TRACK_URL = 'https://music.yandex.ru/album/100/track/200'
MTS_URL = 'https://mts-music-spo.onelink.me/AbCdEf'


class TestLinkParser:
    def test_init(self):
        parser = LinkParser()
        assert 'Spotify' in parser.parsers
        assert 'YandexMusic' in parser.parsers
        assert 'MTS' in parser.parsers

    async def test_unknown_link_returns_none(self):
        """Ссылка не из списка сервисов — None, а не ошибка."""
        assert await parse_link('https://youtube.com/watch?v=1') is None

    async def test_youtube_not_mistaken_for_service(self):
        parser = LinkParser()
        result = await parser.parse_link('https://youtube.com/watch?v=1')
        assert result is None

    async def test_parser_exception_becomes_error_dict(self):
        parser = LinkParser()
        with patch.object(
            parser.parsers['Spotify'], 'parse', new=AsyncMock(side_effect=RuntimeError('boom'))
        ):
            result = await parser.parse_link(SPOTIFY_URL)
        assert 'error' in result

    async def test_spotify_link_routed_to_spotify_parser(self):
        parser = LinkParser()
        expected = {
            'url': SPOTIFY_URL,
            'original_service': SERVICES['Spotify'],
            'title': 'Song',
            'artists': 'Artist',
        }
        with patch.object(
            parser.parsers['Spotify'], 'parse', new=AsyncMock(return_value=expected)
        ) as mock_parse:
            result = await parser.parse_link(SPOTIFY_URL)
        mock_parse.assert_called_once_with(SPOTIFY_URL)
        assert result == expected


class TestYandexParser:
    async def test_requires_track_id(self):
        """Ссылка-поиск без ID трека раньше возвращала фейковые данные."""
        parser = YandexParser(SERVICES['YandexMusic'])
        result = await parser.parse('https://music.yandex.ru/search?text=test')
        assert 'error' in result

    async def test_no_token_returns_error(self):
        parser = YandexParser(SERVICES['YandexMusic'])
        with patch('src.link_parser.get_yandex_client', return_value=None):
            result = await parser.parse(YANDEX_ALBUM_TRACK_URL)
        assert 'error' in result

    async def test_success(self):
        parser = YandexParser(SERVICES['YandexMusic'])

        class FakeArtist:
            name = 'Artist Name'

        class FakeTrack:
            title = 'Track Title'
            artists = [FakeArtist()]

        client = MagicMock()
        client.tracks.return_value = [FakeTrack()]
        with patch('src.link_parser.get_yandex_client', return_value=client):
            result = await parser.parse(YANDEX_ALBUM_TRACK_URL)

        assert result['title'] == 'Track Title'
        assert result['artists'] == 'Artist Name'
        client.tracks.assert_called_once_with(['200'])

    async def test_missing_track_returns_error(self):
        parser = YandexParser(SERVICES['YandexMusic'])
        client = MagicMock()
        client.tracks.return_value = []
        with patch('src.link_parser.get_yandex_client', return_value=client):
            result = await parser.parse(YANDEX_ALBUM_TRACK_URL)
        assert 'error' in result


class TestSpotifyParser:
    async def test_success(self):
        parser = SpotifyParser(SERVICES['Spotify'])
        html = '''
        <html><head>
        <meta property="og:title" content="Song Title">
        <meta name="music:musician_description" content="Artist Name">
        </head><body></body></html>
        '''
        with patch('src.link_parser.aiohttp.ClientSession') as session_cls:
            _mock_aiohttp_response(session_cls, html, status=200)
            result = await parser.parse(SPOTIFY_URL)

        assert result['title'] == 'Song Title'
        assert result['artists'] == 'Artist Name'

    async def test_no_title_is_error(self):
        parser = SpotifyParser(SERVICES['Spotify'])
        _mock_aiohttp_response(
            patch('src.link_parser.aiohttp.ClientSession').start(),
            '<html><head></head><body></body></html>',
            status=200,
        )
        with patch('src.link_parser.aiohttp.ClientSession') as session_cls:
            _mock_aiohttp_response(session_cls, '<html></html>', status=200)
            result = await parser.parse(SPOTIFY_URL)
        assert 'error' in result

    async def test_http_error_is_error(self):
        parser = SpotifyParser(SERVICES['Spotify'])
        with patch('src.link_parser.aiohttp.ClientSession') as session_cls:
            _mock_aiohttp_response(session_cls, '', status=404)
            result = await parser.parse(SPOTIFY_URL)
        assert 'error' in result


class TestMTSParser:
    async def test_h1_title_split(self):
        parser = MTSParser(SERVICES['MTS'])
        html = '<html><body><h1 data-testid="playlist-title" itemprop="name">Artist - Title</h1></body></html>'
        with patch('src.link_parser.aiohttp.ClientSession') as session_cls:
            _mock_aiohttp_response(session_cls, html, status=200)
            result = await parser.parse(MTS_URL)

        assert result['title'] == 'Title'
        assert result['artists'] == 'Artist'

    async def test_og_title_fallback(self):
        parser = MTSParser(SERVICES['MTS'])
        html = (
            '<html><head><meta property="og:title" content="Song - слушать песню онлайн">'
            '</head><body></body></html>'
        )
        with patch('src.link_parser.aiohttp.ClientSession') as session_cls:
            _mock_aiohttp_response(session_cls, html, status=200)
            result = await parser.parse(MTS_URL)

        assert result['title'] == 'Song'
        assert result['artists'] == 'Unknown Artist'

    async def test_nothing_found_is_error(self):
        parser = MTSParser(SERVICES['MTS'])
        with patch('src.link_parser.aiohttp.ClientSession') as session_cls:
            _mock_aiohttp_response(session_cls, '<html></html>', status=200)
            result = await parser.parse(MTS_URL)
        assert 'error' in result


def _mock_aiohttp_response(session_cls, html, status):
    """Подменяет aiohttp-сессию ответом с заданным html и статусом."""
    from unittest.mock import MagicMock

    response = MagicMock()
    response.status = status
    response.text = AsyncMock(return_value=html)
    response.url = 'https://example.com/final'

    get_ctx = MagicMock()
    get_ctx.__aenter__ = AsyncMock(return_value=response)
    get_ctx.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=get_ctx)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session_cls.return_value = ctx
    return session_cls
