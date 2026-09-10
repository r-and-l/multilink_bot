"""Нечёткое сравнение треков: проверяем, что найденный в стороннем сервисе
результат — действительно тот же трек, а не случайный первый из выдачи."""
import difflib
import re
from functools import lru_cache

# Пустые слова и типовые мусорные приписки в названиях треков
STOP_WORDS = {'feat', 'ft', 'featuring', 'the', 'a', 'an', '&', 'and'}

# Приписки-версии важны для идентичности трека, но мешают сравнивать
# базовое название, поэтому учитываем их отдельным бонусом
VERSION_RE = re.compile(
    r'\((?:[^)]*\)?(?:remix|rmx|version|edit|mix|radio|live|extended|instrumental|acoustic)[^)]*)\)'
    r'|\[(?:[^\]]*(?:remix|rmx|version|edit|mix|radio|live|extended|instrumental|acoustic)[^\]]*)\]',
    re.IGNORECASE,
)


@lru_cache(maxsize=4096)
def _normalize(text):
    """Нижний регистр, только буквы/цифры, без стоп-слов и пунктуации."""
    text = text or ''
    text = text.lower()
    text = VERSION_RE.sub(' ', text)
    tokens = re.findall(r'[a-zа-яё0-9]+', text)
    tokens = [t for t in tokens if t not in STOP_WORDS]
    return tuple(tokens)


@lru_cache(maxsize=4096)
def _title_similarity(a, b):
    """0..1: похожесть названий.

    Считаем пословно: целиком совпавшие слова дают полный вклад, близкие
    (опечатки) — долю своей похожести. Так «Lights» и «Sights» не
    засчитываются как одно слово, а «Shivers» и «Shivers» — да.
    """
    if not a or not b:
        return 0.0
    words_a = a.split()
    words_b = b.split()
    if not words_a or not words_b:
        return 0.0

    matched_b = [False] * len(words_b)
    score = 0.0
    for wa in words_a:
        best_j, best_ratio = None, 0.0
        for j, wb in enumerate(words_b):
            if matched_b[j]:
                continue
            ratio = 1.0 if wa == wb else difflib.SequenceMatcher(None, wa, wb).ratio()
            if ratio > best_ratio:
                best_j, best_ratio = j, ratio
        # Слова считаем совпавшими только при почти точном совпадении
        if best_j is not None and best_ratio >= 0.9:
            matched_b[best_j] = True
            score += 1.0
    longer = max(len(words_a), len(words_b))
    return score / longer


@lru_cache(maxsize=4096)
def _artist_match(artists_a, artists_b):
    """True, если хоть один артист совпал (по подстроке нормализованных имён).

    Артисты «Artist A, Artist B» против «Artist A» — это тот же трек
    (feat-коллаборации), поэтому достаточно одного пересечения.
    """
    for a in artists_a:
        for b in artists_b:
            if not a or not b:
                continue
            # Короткие имена сравниваем строгим совпадением токенов,
            # длинные — на 80% похожести
            if a == b:
                return True
            if len(a) > 3 and len(b) > 3 and (
                a in b or b in a or _title_similarity(a, b) >= 0.8
            ):
                return True
    return False


def _split_artists(artists_str):
    """Разбивает строку артистов по разделителям и нормализует каждую часть."""
    if not artists_str:
        return ()
    parts = re.split(r'\s*,\s*|\s*&\s*|\s+and\s+|\s+x\s+', artists_str.lower())
    return tuple(' '.join(_normalize(p)) for p in parts if p and p.strip())


def is_same_track(expected, candidate, title_threshold=0.75):
    """Сравнивает исходный трек с кандидатом из поиска.

    Args:
        expected: dict с ключами 'title' и 'artists' (исходный трек)
        candidate: dict с 'title' и 'artists' (найденный трек)
        title_threshold: минимальная похожесть названия

    Возвращает True, если с высокой вероятностью это тот же трек.
    """
    if not expected or not candidate:
        return False

    exp_title = ' '.join(_normalize(expected.get('title', '')))
    cand_title = ' '.join(_normalize(candidate.get('title', '')))
    if not exp_title:
        return False

    title_score = _title_similarity(exp_title, cand_title)
    if title_score < title_threshold:
        return False

    exp_artists = _split_artists(expected.get('artists', ''))
    cand_artists = _split_artists(candidate.get('artists', ''))
    if not exp_artists or not cand_artists:
        # Нет данных об артистах — доверяем совпавшему названию
        return title_score >= 0.9

    return _artist_match(exp_artists, cand_artists)


def pick_best_match(expected, candidates, title_threshold=0.75):
    """Выбирает из кандидатов первый трек, совпадающий с исходным.

    Возвращает элемент candidates или None. Кандидаты должны быть
    отсортированы по релевантности (так их отдают сервисы).
    """
    for candidate in candidates:
        if is_same_track(expected, candidate, title_threshold):
            return candidate
    return None
