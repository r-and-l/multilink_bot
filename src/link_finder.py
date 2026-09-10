"""Поиск трека в остальных сервисах: по данным одного сервиса строим ссылки
на этот же трек в других."""
import asyncio
import logging
import urllib.parse
from abc import ABC, abstractmethod

from .clients import get_spotify_client, get_yandex_client
from .constants import SERVICES
from .matching import is_same_track, pick_best_match

logger = logging.getLogger(__name__)


def _search_url(base, track_info):
    """URL страницы поиска с закодированным запросом «артист - название»."""
    query = urllib.parse.quote(f"{track_info['artists']} - {track_info['title']}")
    return f'{base}search?text={query}'


def _spotify_search_url(track_info):
    """Рабочий формат поиска Spotify: /search/<запрос>, не ?text=."""
    query = urllib.parse.quote(f"{track_info['artists']} {track_info['title']}")
    return f'https://open.spotify.com/search/{query}'


class Finder(ABC):
    """Базовый класс поиска трека в стороннем сервисе"""

    def __init__(self, service_info):
        self.service = service_info

    @abstractmethod
    async def find(self, track_info):
        """Возвращает dict {'service': str, 'url': str | None}."""
        raise NotImplementedError


class SpotifyFinder(Finder):
    def _search_sync(self, track_info):
        """Синхронный поиск через Spotify Web API; вызывается через to_thread.

        Строим field-фильтры artist:/track: — они дают заметно точнее
        выдачу, чем сырой запрос «артист - название». Убираем оскорбительный
        для Spotify синтаксис «feat», который ломает фильтры.
        """
        sp = get_spotify_client()
        if sp is None:
            return None

        artists = [a.strip() for a in track_info['artists'].split(',') if a.strip()]
        queries = []
        if artists:
            artist_part = ' '.join(f'artist:"{a}"' for a in artists[:2])
            queries.append(f'{artist_part} track:"{track_info["title"]}"')
        queries.append(f'track:"{track_info["title"]}"')
        queries.append(f"{track_info['artists']} {track_info['title']}")

        for query in queries:
            results = sp.search(q=query, type='track', limit=5)
            items = results.get('tracks', {}).get('items', [])
            if not items:
                continue

            candidates = [
                {
                    'title': item['name'],
                    'artists': ', '.join(a['name'] for a in item['artists']),
                    'url': item['external_urls']['spotify'],
                }
                for item in items
            ]
            match = pick_best_match(track_info, candidates)
            if match:
                return match['url']
        return None

    async def find(self, track_info):
        fallback_url = _spotify_search_url(track_info)
        try:
            url = await asyncio.to_thread(self._search_sync, track_info)
            return {'service': self.service['name'], 'url': url or fallback_url}
        except Exception:
            logger.exception('Ошибка поиска в Spotify')
            return {'service': self.service['name'], 'url': fallback_url}


class YandexFinder(Finder):
    def _search_sync(self, track_info):
        """Синхронный поиск через Yandex SDK; вызывается через to_thread."""
        client = get_yandex_client()
        if client is None:
            return None

        track_name = f"{track_info['artists']} - {track_info['title']}"
        result = client.search(track_name, type_='track', page=0)

        candidates = []
        if result:
            if result.best and result.best.type == 'track' and result.best.result:
                candidates.append(result.best.result)
            if result.tracks and result.tracks.results:
                candidates.extend(result.tracks.results[:4])

        for track in candidates:
            candidate = {
                'title': track.title,
                'artists': ', '.join(a.name for a in track.artists) if track.artists else '',
            }
            if is_same_track(track_info, candidate) and track.albums:
                return (
                    f'https://music.yandex.ru/album/{track.albums[0].id}/track/{track.id}'
                )
        return None

    async def find(self, track_info):
        fallback_url = _search_url('https://music.yandex.ru/', track_info)
        try:
            url = await asyncio.to_thread(self._search_sync, track_info)
            return {'service': self.service['name'], 'url': url or fallback_url}
        except Exception:
            logger.exception('Ошибка поиска в Yandex Music')
            return {'service': self.service['name'], 'url': fallback_url}


class MTSFinder(Finder):
    async def find(self, track_info):
        # У MTS Music нет публичного API стабильных ссылок на трек:
        # VK-поиск отдаёт только прямой mp3-поток, живущий считанные часы,
        # поэтому всегда отдаём ссылку на страницу поиска
        return {
            'service': self.service['name'],
            'url': _search_url('https://music.mts.ru/', track_info),
        }


class LinkFinder:
    def __init__(self):
        self.finders = [
            SpotifyFinder(SERVICES['Spotify']),
            YandexFinder(SERVICES['YandexMusic']),
            MTSFinder(SERVICES['MTS']),
        ]

    async def _find_one(self, finder, track_info):
        """Обёртка-предохранитель: даже если у finder внутренний баг,
        пользователь получит ссылку на поиск, а не упавший весь ответ."""
        try:
            return await finder.find(track_info)
        except Exception:
            logger.exception('Критическая ошибка поиска в %s', finder.service['name'])
            return {
                'service': finder.service['name'],
                'url': _search_url(finder.service['search_base'], track_info),
            }

    async def find_link(self, track_info):
        original_name = (track_info.get('original_service') or {}).get('name')
        tasks = [
            self._find_one(finder, track_info)
            for finder in self.finders
            if finder.service['name'] != original_name
        ]
        # Все сервисы ищем параллельно: поодиночке не укладываемся в лимит
        # serverless-функции
        return await asyncio.gather(*tasks)


async def find_link(track_info):
    """Ищет трек во всех сервисах, кроме исходного.

    Возвращает список [{'service': str, 'url': str | None}, ...].
    Каждый finder сам обрабатывает свои ошибки, поэтому исключений
    наружу не просачивается.
    """
    finder = LinkFinder()
    return await finder.find_link(track_info)
