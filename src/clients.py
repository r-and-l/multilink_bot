"""Разные HTTP-клиенты внешних сервисов, кэшируются на уровне процесса.

Клиенты Yandex Music и Spotify дорогие в создании (по несколько сетевых
запросов на инициализацию), а Vercel-функция живёт дольше одного вызова.
Поэтому создаём их один раз на процесс и переиспользуем в «тёплых» вызовах.
Синхронные клиенты вызываются из async-кода через asyncio.to_thread().
"""
import logging
import os
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_yandex_client = None
_spotify_client = None

# Свежесть поиска в секундах: если свежее — ищем точную ссылку,
# иначе отдаём ссылку на страницу поиска
SEARCH_CACHE_TTL = 3600

# Настройки HTTP-клиентов: сервисы бывают медленные, не висим на них вечно
HTTP_TIMEOUT = 15


def get_yandex_client():
    """Возвращает кэшированный клиент Yandex Music или None без токена."""
    global _yandex_client
    if _yandex_client is not None:
        return _yandex_client

    token = os.getenv('YANDEX_MUSIC_TOKEN')
    if not token:
        logger.warning('YANDEX_MUSIC_TOKEN не задан — Yandex Music будет недоступен')
        return None

    with _lock:
        if _yandex_client is not None:
            return _yandex_client
        from yandex_music import Client
        # fetch_account=False: не запрашиваем данные аккаунта — быстрее и
        # не зависит от прав токена
        client = Client(token, fetch_account=False).init()
        logger.info('Yandex Music client initialized')
        _yandex_client = client
        return _yandex_client


def get_spotify_client():
    """Возвращает кэшированный клиент Spotify или None без ключей."""
    global _spotify_client
    if _spotify_client is not None:
        return _spotify_client

    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    if not client_id or not client_secret:
        logger.warning('SPOTIFY_CLIENT_ID/SECRET не заданы — Spotify search будет недоступен')
        return None

    with _lock:
        if _spotify_client is not None:
            return _spotify_client
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        client = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret,
            )
        )
        logger.info('Spotify client initialized')
        _spotify_client = client
        return _spotify_client
