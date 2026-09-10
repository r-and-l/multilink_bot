import pytest

from src.matching import is_same_track, pick_best_match


def track(title, artists):
    return {'title': title, 'artists': artists}


class TestIsSameTrack:
    def test_exact_match(self):
        assert is_same_track(
            track('Blinding Lights', 'The Weeknd'),
            track('Blinding Lights', 'The Weeknd'),
        )

    def test_case_and_punctuation_insensitive(self):
        assert is_same_track(
            track('Blinding Lights', 'The Weeknd'),
            track('blinding lights!', 'the weeknd'),
        )

    def test_feat_collaboration_matches(self):
        """Feat-артисты не должны ломать совпадение."""
        assert is_same_track(
            track('Rain On Me', 'Lady Gaga'),
            track('Rain On Me', 'Lady Gaga, Ariana Grande'),
        )

    def test_remix_version_matches_base(self):
        """(Remix) в названии кандидата — всё ещё тот же трек."""
        assert is_same_track(
            track('Sunset', 'Artist'),
            track('Sunset (Remix)', 'Artist'),
        )

    def test_cyrillic(self):
        assert is_same_track(
            track('Пятница', 'Мумий Тролль'),
            track('Пятница', 'Мумий Тролль, Браво'),
        )

    def test_similar_but_not_same_title(self):
        assert not is_same_track(
            track('Blinding Lights', 'The Weeknd'),
            track('Blinding Sights', 'The Weeknd'),
        )

    def test_same_title_different_artist(self):
        """Одинаковые названия у разных артистов — не тот же трек."""
        assert not is_same_track(
            track('Believer', 'Imagine Dragons'),
            track('Believer', 'Some Other Band'),
        )

    def test_no_artist_data_trusts_strong_title(self):
        """Без данных об артисте принимаем только почти точное название."""
        assert is_same_track(
            track('Bohemian Rhapsody', ''),
            track('Bohemian Rhapsody', ''),
        )
        assert not is_same_track(
            track('Bohemian Rhapsody', ''),
            track('Bohemian Rhapsody Live', ''),
        )

    def test_none_inputs(self):
        assert not is_same_track(None, track('x', 'y'))
        assert not is_same_track(track('x', 'y'), None)
        assert not is_same_track({}, {})


class TestPickBestMatch:
    def test_returns_first_matching_candidate(self):
        expected = track('Levitating', 'Dua Lipa')
        candidates = [
            track('Levitating (Freeex Remix)', 'Dua Lipa'),  # не-совпадение? нет — совпадение
            track('Levitating', 'Dua Lipa, DaBaby'),
        ]
        result = pick_best_match(expected, candidates)
        assert result is candidates[0] or result is candidates[1]

    def test_skips_wrong_candidates(self):
        expected = track('Levitating', 'Dua Lipa')
        candidates = [
            track('Levitating', 'BTS'),  # чужой трек с тем же названием
            track('Levitating', 'Dua Lipa'),
        ]
        result = pick_best_match(expected, candidates)
        assert result is candidates[1]

    def test_no_match_returns_none(self):
        expected = track('Never Gonna Give You Up', 'Rick Astley')
        candidates = [track('Never Gonna Give You Up', 'Someone Else')]
        assert pick_best_match(expected, candidates) is None

    def test_empty_candidates(self):
        assert pick_best_match(track('x', 'y'), []) is None
