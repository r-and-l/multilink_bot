import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import src.link_finder as link_finder
from src.constants import SERVICES
from src.link_finder import LinkFinder

TRACK = {
    'url': 'https://open.spotify.com/track/123',
    'original_service': SERVICES['Spotify'],
    'title': 'Test Song',
    'artists': 'Test Artist',
}


def spotify_search_response(items, id_offset=0):
    """Формат ответа Spotify Web API /v1/search."""
    return {
        'tracks': {
            'items': [
                {
                    'name': name,
                    'artists': [{'name': artist}],
                    'external_urls': {
                        'spotify': f'https://open.spotify.com/track/{i + id_offset}'
                    },
                }
                for i, (name, artist) in enumerate(items)
            ]
        }
    }


class TestLinkFinder:
    async def test_original_service_excluded(self):
        finder = LinkFinder()
        results = await finder.find_link(TRACK)

        names = [r['service'] for r in results]
        assert SERVICES['Spotify']['name'] not in names
        assert SERVICES['YandexMusic']['name'] in names
        assert SERVICES['MTS']['name'] in names

    async def test_all_results_have_service_and_url(self):
        finder = LinkFinder()
        results = await finder.find_link(TRACK)
        for result in results:
            assert set(result) == {'service', 'url'}
            assert result['url'] is not None

    async def test_finders_run_in_parallel(self):
        """Поиск не должен быть последовательным: суммарное время — не сумма."""
        import asyncio

        finder = LinkFinder()
        delay = 0.3

        async def slow_find(self, track_info):
            await asyncio.sleep(delay)
            return {'service': self.service['name'], 'url': 'https://x'}

        with patch.object(link_finder.SpotifyFinder, 'find', slow_find):
            with patch.object(link_finder.YandexFinder, 'find', slow_find):
                with patch.object(link_finder.MTSFinder, 'find', slow_find):
                    start = asyncio.get_event_loop().time()
                    results = await finder.find_link(
                        {**TRACK, 'original_service': None}
                    )
                    elapsed = asyncio.get_event_loop().time() - start

        assert len(results) == 3
        # Последовательный поиск занял бы ~0.9 c (3 × delay)
        assert elapsed < delay * 2.5

    async def test_finder_error_does_not_break_others(self):
        """Один упавший сервис не должен ронять весь gather."""
        finder = LinkFinder()

        async def failing_find(self, track_info):
            raise RuntimeError('api down')

        with patch.object(link_finder.YandexFinder, 'find', failing_find):
            results = await finder.find_link(TRACK)

        # Упавший сервис замещён ссылкой на поиск, остальные на месте
        names = [r['service'] for r in results]
        assert SERVICES['YandexMusic']['name'] in names
        assert SERVICES['MTS']['name'] in names
        for result in results:
            assert result['url'] is not None


class TestSpotifyFinder:
    async def test_no_credentials_returns_search_url(self):
        from src.link_finder import SpotifyFinder

        sf = SpotifyFinder(SERVICES['Spotify'])
        with patch('src.link_finder.get_spotify_client', return_value=None):
            result = await sf.find(TRACK)

        # Рабочий формат Spotify-поиска: /search/<query>
        assert result['url'].startswith('https://open.spotify.com/search/')
        assert 'search?text=' not in result['url']

    async def test_matching_candidate_wins_over_first_result(self):
        """Первый результат — чужой трек, совпадение лежит глубже."""
        from src.link_finder import SpotifyFinder

        sf = SpotifyFinder(SERVICES['Spotify'])
        sp = MagicMock()
        # Первый запрос (с фильтрами): только нерелевантные треки;
        # второй (track:"...") — нужный
        sp.search.side_effect = [
            spotify_search_response([('Unrelated Song', 'Other Artist')]),
            spotify_search_response([('Test Song', 'Test Artist')], id_offset=1),
        ]
        with patch('src.link_finder.get_spotify_client', return_value=sp):
            result = await sf.find(TRACK)

        assert result['url'] == 'https://open.spotify.com/track/1'

    async def test_no_match_falls_back_to_search_url(self):
        from src.link_finder import SpotifyFinder

        sf = SpotifyFinder(SERVICES['Spotify'])
        sp = MagicMock()
        sp.search.return_value = spotify_search_response([('Unrelated Song', 'Other Artist')])
        with patch('src.link_finder.get_spotify_client', return_value=sp):
            result = await sf.find(TRACK)

        assert result['url'].startswith('https://open.spotify.com/search/')

    async def test_uses_field_filters_first(self):
        """Первый запрос должен использовать artist:/track: фильтры."""
        from src.link_finder import SpotifyFinder

        sf = SpotifyFinder(SERVICES['Spotify'])
        sp = MagicMock()
        sp.search.return_value = spotify_search_response([('Test Song', 'Test Artist')])
        with patch('src.link_finder.get_spotify_client', return_value=sp):
            await sf.find(TRACK)

        first_query = sp.search.call_args_list[0][1]['q']
        assert 'artist:"Test Artist"' in first_query
        assert 'track:"Test Song"' in first_query


class TestYandexFinder:
    def _ym_track(self, title, artist, album_id=100, track_id=200):
        track = MagicMock()
        track.title = title
        track.id = track_id
        artist_mock = MagicMock()
        artist_mock.name = artist
        track.artists = [artist_mock]
        album = MagicMock()
        album.id = album_id
        track.albums = [album]
        return track

    async def test_no_token_returns_search_url(self):
        from src.link_finder import YandexFinder

        yf = YandexFinder(SERVICES['YandexMusic'])
        with patch('src.link_finder.get_yandex_client', return_value=None):
            result = await yf.find(TRACK)

        assert result['url'].startswith('https://music.yandex.ru/search?text=')
        assert ' ' not in result['url'].split('=')[-1]

    async def test_matching_track_returns_album_url(self):
        from src.link_finder import YandexFinder

        yf = YandexFinder(SERVICES['YandexMusic'])
        client = MagicMock()

        result_search = MagicMock()
        best = MagicMock()
        best.type = 'track'
        best.result = self._ym_track('Test Song', 'Test Artist')
        result_search.best = best
        result_search.tracks = None
        client.search.return_value = result_search

        with patch('src.link_finder.get_yandex_client', return_value=client):
            result = await yf.find(TRACK)

        assert result['url'] == 'https://music.yandex.ru/album/100/track/200'

    async def test_wrong_track_falls_back_to_search(self):
        """Выдача Яндекса не совпала с исходным треком — отдаём поиск,
        а не ссылку на чужой трек."""
        from src.link_finder import YandexFinder

        yf = YandexFinder(SERVICES['YandexMusic'])
        client = MagicMock()

        result_search = MagicMock()
        best = MagicMock()
        best.type = 'track'
        best.result = self._ym_track('Completely Different', 'Other Artist')
        result_search.best = best
        result_search.tracks = None
        client.search.return_value = result_search

        with patch('src.link_finder.get_yandex_client', return_value=client):
            result = await yf.find(TRACK)

        assert result['url'].startswith('https://music.yandex.ru/search?text=')


class TestMTSFinder:
    async def test_always_returns_search_url(self):
        """У MTS нет стабильных ссылок — всегда отдаём поиск без сети."""
        from src.link_finder import MTSFinder

        mf = MTSFinder(SERVICES['MTS'])
        result = await mf.find(TRACK)

        assert result['url'].startswith('https://music.mts.ru/search?text=')
        assert ' ' not in result['url'].split('=')[-1]
