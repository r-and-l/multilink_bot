"""Парсинг ссылок на трек: определяем сервис, вытаскиваем название и артистов."""
import asyncio
import logging
import re
from abc import ABC, abstractmethod
from urllib.parse import parse_qsl, unquote, urlparse

import aiohttp
from bs4 import BeautifulSoup
from yandex_music.exceptions import UnauthorizedError

from .clients import HTTP_TIMEOUT, get_yandex_client
from .constants import SERVICES

logger = logging.getLogger(__name__)

# Страница Spotify отдаёт полные данные в og-мета только «чистому» UA
SPOTIFY_UA = 'TelegramBot (like Twitterbot) Android'
BROWSER_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


class Parser(ABC):
    """Базовый класс парсера конкретного сервиса"""

    def __init__(self, service_info):
        self.service = service_info

    @abstractmethod
    async def parse(self, url):
        """Возвращает dict с ключами url/title/artists/original_service
        либо {'error': ...}."""
        raise NotImplementedError


class SpotifyParser(Parser):
    async def parse(self, url):
        # Спотифай редиректит короткие ссылки (spotify.link/...) на
        # канонические open.spotify.com/track/<id>
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        ) as session:
            async with session.get(
                url,
                headers={'User-Agent': SPOTIFY_UA},
                allow_redirects=True,
            ) as response:
                if response.status != 200:
                    return {'error': f'Spotify вернул HTTP {response.status}'}
                html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')

        og_title = soup.find('meta', property='og:title')
        artists_meta = soup.find(
            'meta', {'name': 'music:musician_description'}
        ) or soup.find('meta', {'property': 'music:musician_description'})

        title = og_title.get('content', '').strip() if og_title else ''
        artists = artists_meta.get('content', '').strip() if artists_meta else ''

        if not title:
            return {'error': 'Не удалось извлечь название трека из Spotify'}

        return {
            'url': url,
            'original_service': self.service,
            'title': title,
            'artists': artists or 'Unknown Artist',
        }


class YandexParser(Parser):
    # Только страницы трека внутри альбома: для них известен track_id
    TRACK_ID_RE = re.compile(r'/track/(\d+)')

    async def parse(self, url):
        match = self.TRACK_ID_RE.search(url)
        if not match:
            # Ссылки вида /album/<id>/track/<id> или /search — не тянем
            # страницу ради заголовка, отдаём ошибку
            return {
                'error': (
                    'Не удалось извлечь ID трека из ссылки Яндекс Музыки '
                    '(ожидается ссылка вида /album/.../track/... или /track/...)'
                )
            }

        track_id = match.group(1)

        client = get_yandex_client()
        if client is None:
            return {'error': 'YANDEX_MUSIC_TOKEN не задан — нечем парсить трек'}

        try:
            # Синхронный SDK, выносим из event loop
            tracks = await asyncio.to_thread(client.tracks, [track_id])
            track = tracks[0] if tracks else None
            if track is None:
                return {'error': f'Трек {track_id} не найден в Яндекс Музыке'}

            return {
                'url': url,
                'original_service': self.service,
                'title': track.title,
                'artists': ', '.join(a.name for a in track.artists),
            }
        except UnauthorizedError:
            logger.error('Yandex Music токен невалиден')
            return {'error': 'Токен Yandex Music невалиден или истёк'}
        except Exception as e:
            logger.exception('Ошибка парсинга Yandex трека %s', track_id)
            return {'error': f'Ошибка при получении трека из Яндекс Музыки: {e}'}


class MTSParser(Parser):
    async def parse(self, url):
        headers = {
            'User-Agent': BROWSER_UA,
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.5',
        }
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
            ) as session:
                async with session.get(url, headers=headers, allow_redirects=True) as response:
                    # OneLink-редирект ведёт на страницу приложения,
                    # а не трека; заголовок трека лежит в deep_link_value
                    deep_link = self._extract_deep_link(response)
                    if deep_link:
                        async with session.get(deep_link, headers=headers) as track_response:
                            html = await track_response.text()
                            track_url = str(track_response.url)
                    else:
                        html = await response.text()
                        track_url = str(response.url)
        except aiohttp.ClientError as e:
            return {'error': f'Не удалось загрузить страницу MTS: {e}'}

        soup = BeautifulSoup(html, 'html.parser')
        return self._extract_track_info(soup, url, track_url)

    def _extract_deep_link(self, response):
        """OneLink-ссылки ведут на страницу призыва скачать приложение;
        настоящий URL трека приходит в query-параметре deep_link_value."""
        parsed = urlparse(str(response.url))
        query = dict(parse_qsl(parsed.query))
        deep_link = query.get('deep_link_value')
        if not deep_link:
            return None
        # Значение приходит одноуровнево закодированным повторно
        if deep_link.startswith('https%3A%2F%2F') or '%2F' in deep_link:
            deep_link = unquote(deep_link)
        return deep_link if deep_link.startswith('http') else None

    def _extract_track_info(self, soup, url, track_url):
        track_title_elem = soup.find(
            'h1', {'data-testid': 'playlist-title', 'itemprop': 'name'}
        )
        if track_title_elem:
            full_title = track_title_elem.get_text(strip=True)
            if ' - ' in full_title:
                artists, title = full_title.split(' - ', 1)
                return {
                    'url': url,
                    'original_service': self.service,
                    'title': title.strip(),
                    'artists': artists.strip(),
                }
            return {
                'url': url,
                'original_service': self.service,
                'title': full_title.strip(),
                'artists': 'Unknown Artist',
            }

        # Fallback на og:title
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            for suffix in (' - слушать песню онлайн', ' — слушать песню онлайн'):
                if suffix in title:
                    title = title.split(suffix)[0].strip()
                    break
            return {
                'url': url,
                'original_service': self.service,
                'title': title,
                'artists': 'Unknown Artist',
            }

        return {'error': 'Не удалось извлечь название трека со страницы MTS'}


class LinkParser:
    def __init__(self):
        self.services = SERVICES
        self.parsers = {
            'Spotify': SpotifyParser(self.services['Spotify']),
            'YandexMusic': YandexParser(self.services['YandexMusic']),
            'MTS': MTSParser(self.services['MTS']),
        }

    async def parse_link(self, url):
        for name, parser in self.parsers.items():
            if parser.service['regex'].match(url):
                try:
                    return await parser.parse(url)
                except Exception:
                    logger.exception('Непредвиденная ошибка парсинга %s', name)
                    return {'error': 'Ошибка при разборе ссылки'}
        return None


async def parse_link(url):
    """Определяет сервис по ссылке и возвращает данные о треке.

    Возвращает None, если ссылка не опознана как ссылка на музыку.
    Возвращает {'error': ...}, если сервис опознан, но трек получить не удалось.
    """
    parser = LinkParser()
    return await parser.parse_link(url)
