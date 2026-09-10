import pytest

from src.markdown import escape_markdown


class TestEscapeMarkdown:
    def test_escapes_special_chars(self):
        assert escape_markdown('a.b') == 'a\\.b'
        assert escape_markdown('x*y') == 'x\\*y'
        assert escape_markdown('a(b)c') == 'a\\(b\\)c'
        assert escape_markdown('a_b') == 'a\\_b'

    def test_regular_text_unchanged(self):
        assert escape_markdown('Hello World') == 'Hello World'
        assert escape_markdown('Просто текст') == 'Просто текст'

    def test_empty_and_none(self):
        assert escape_markdown('') == 'N/A'
        assert escape_markdown(None) == 'N/A'

    def test_full_set_of_markdownv2_chars(self):
        # Все спецсимволы MarkdownV2 по документации Telegram
        text = '*_`[]()~>#+-=|{}.!'
        escaped = escape_markdown(text)
        # После снятия экранирования получается исходный текст
        assert escaped.replace('\\', '') == text
        assert escaped.count('\\') == len(text)
