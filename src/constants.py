import re

SPOTIFY_REGEX = re.compile(r'https?://(open\.spotify\.com|spotify\.link)/[^\s]+', re.IGNORECASE)
YANDEX_MUSIC_REGEX = re.compile(r'https?://music\.yandex\.ru/[^\s]+', re.IGNORECASE)
MTS_MUSIC_REGEX = re.compile(r'https?://mts-music-spo\.onelink\.me/[^\s]+', re.IGNORECASE)

SERVICES = {
    'Spotify': {
        'name': '🟢 Spotify',
        'regex': SPOTIFY_REGEX,
        'search_base': 'https://open.spotify.com/search/',
    },
    'YandexMusic': {
        'name': '🟠 Yandex Music',
        'regex': YANDEX_MUSIC_REGEX,
        'search_base': 'https://music.yandex.ru/',
    },
    'MTS': {
        'name': '🟣 MTS Music',
        'regex': MTS_MUSIC_REGEX,
        'search_base': 'https://music.mts.ru/',
    },
}