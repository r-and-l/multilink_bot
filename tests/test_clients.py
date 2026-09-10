import pytest
from unittest.mock import MagicMock, patch

from src import clients


class TestClientCache:
    def setup_method(self):
        clients._yandex_client = None
        clients._spotify_client = None

    def test_no_yandex_token_returns_none(self):
        with patch.dict('os.environ', {}, clear=True):
            assert clients.get_yandex_client() is None

    def test_no_spotify_credentials_returns_none(self):
        with patch.dict('os.environ', {}, clear=True):
            assert clients.get_spotify_client() is None

    def test_yandex_client_created_once(self):
        with patch.dict(
            'os.environ', {'YANDEX_MUSIC_TOKEN': 'tok'}, clear=True
        ):
            with patch('yandex_music.Client') as client_cls:
                instance = MagicMock()
                client_cls.return_value = instance
                instance.init.return_value = instance

                first = clients.get_yandex_client()
                second = clients.get_yandex_client()

        assert first is second
        # SDK-клиент (и его сетевая инициализация) создан один раз
        client_cls.assert_called_once()
        instance.init.assert_called_once()

    def test_spotify_client_created_once(self):
        with patch.dict(
            'os.environ',
            {'SPOTIFY_CLIENT_ID': 'id', 'SPOTIFY_CLIENT_SECRET': 'sec'},
            clear=True,
        ):
            with patch('spotipy.Spotify') as spotify_cls:
                instance = MagicMock()
                spotify_cls.return_value = instance

                first = clients.get_spotify_client()
                second = clients.get_spotify_client()

        assert first is second
        spotify_cls.assert_called_once()
