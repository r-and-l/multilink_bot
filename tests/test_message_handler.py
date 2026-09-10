import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import src.message_handler as message_handler
from src.message_handler import BotHandlers, build_response


def make_message(text):
    """Мок апдейта с текстовым сообщением."""
    from telegram import Message, Update

    update = MagicMock(spec=Update)
    message = MagicMock(spec=Message)
    message.text = text
    message.chat_id = 3
    message.reply_text = AsyncMock()
    update.message = message
    return update


def make_inline_update(query):
    from telegram import InlineQuery, Update

    update = MagicMock(spec=Update)
    inline_query = MagicMock(spec=InlineQuery)
    inline_query.query = query
    inline_query.answer = AsyncMock()
    update.inline_query = inline_query
    return update


class TestBotHandlersInit:
    def test_messages_defined(self):
        handlers = BotHandlers()
        assert handlers.welcome_message.startswith('Hello!')
        assert handlers.invalid_message.startswith('Please send')
        assert handlers.error_message


class TestHandleMessage:
    async def test_no_url_replies_invalid(self):
        handlers = BotHandlers()
        update = make_message('Hello world')
        reply = update.message.reply_text
        await handlers.handle_message(update, None)
        reply.assert_called_once_with(handlers.invalid_message)

    async def test_unknown_service_link_replies_invalid(self):
        """Ссылка есть, но не музыкальная — раньше уводило бота в TypeError."""
        handlers = BotHandlers()
        update = make_message('Look: https://youtube.com/watch?v=1')
        with patch(
            'src.message_handler.parse_link', new=AsyncMock(return_value=None)
        ):
            await handlers.handle_message(update, None)
        # Один reply «Parsing…» + edit этого сообщения итоговым текстом
        update.message.reply_text.assert_called_once()
        parsing_msg = update.message.reply_text.return_value
        parsing_msg.edit_text.assert_called_once_with(handlers.invalid_message)

    async def test_parse_error_replies_error_message(self):
        handlers = BotHandlers()
        update = make_message('https://open.spotify.com/track/123')
        with patch(
            'src.message_handler.parse_link',
            new=AsyncMock(return_value={'error': 'boom'}),
        ):
            await handlers.handle_message(update, None)
        update.message.reply_text.assert_called_once()
        parsing_msg = update.message.reply_text.return_value
        parsing_msg.edit_text.assert_called_once_with(handlers.error_message)

    async def test_successful_flow(self):
        from src.constants import SERVICES

        handlers = BotHandlers()
        update = make_message('https://open.spotify.com/track/123')
        data = {
            'url': 'https://open.spotify.com/track/123',
            'original_service': SERVICES['Spotify'],
            'title': 'Test Song',
            'artists': 'Test Artist',
        }
        links = [{'service': SERVICES['YandexMusic']['name'], 'url': 'https://music.yandex.ru/album/1/track/2'}]

        parsing_msg = AsyncMock()
        parsing_msg.edit_text = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=parsing_msg)
        with patch('src.message_handler.parse_link', new=AsyncMock(return_value=data)):
            with patch('src.message_handler.find_link', new=AsyncMock(return_value=links)):
                await handlers.handle_message(update, None)

        update.message.reply_text.assert_called_once()  # «Parsing your link...»
        parsing_msg.edit_text.assert_called_once()
        text = parsing_msg.edit_text.call_args[0][0]
        assert 'Test Song' in text
        assert 'music.yandex.ru/album/1/track/2' in text
        # MarkdownV2 по умолчанию
        assert parsing_msg.edit_text.call_args[1].get('parse_mode') == 'MarkdownV2'

    async def test_pipeline_timeout(self):
        handlers = BotHandlers()
        update = make_message('https://open.spotify.com/track/123')

        async def slow_parse(url):
            import asyncio

            await asyncio.sleep(message_handler.PIPELINE_TIMEOUT + 5)

        parsing_msg = AsyncMock()
        parsing_msg.edit_text = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=parsing_msg)
        with patch('src.message_handler.parse_link', new=AsyncMock(side_effect=slow_parse)):
            await handlers.handle_message(update, None)

        text = parsing_msg.edit_text.call_args[0][0]
        assert text == handlers.timeout_message


class TestInlineQuery:
    async def test_no_url_answers_empty(self):
        """Inline без ссылки раньше падал с UnboundLocalError."""
        handlers = BotHandlers()
        update = make_inline_update('hello')
        answer = update.inline_query.answer
        await handlers.inline_query(update, None)
        answer.assert_called_once()
        assert answer.call_args[0][0] == []

    async def test_with_url_answers_article(self):
        from src.constants import SERVICES

        handlers = BotHandlers()
        update = make_inline_update('https://open.spotify.com/track/123')
        data = {
            'url': 'https://open.spotify.com/track/123',
            'original_service': SERVICES['Spotify'],
            'title': 'Test Song',
            'artists': 'Test Artist',
        }
        links = [{'service': SERVICES['MTS']['name'], 'url': 'https://music.mts.ru/search?text=Test'}]

        answer = update.inline_query.answer
        with patch('src.message_handler.parse_link', new=AsyncMock(return_value=data)):
            with patch('src.message_handler.find_link', new=AsyncMock(return_value=links)):
                await handlers.inline_query(update, None)

        results = answer.call_args[0][0]
        assert len(results) == 1
        assert results[0].id == 'multilink'
        assert 'Test Song' in results[0].input_message_content.message_text


class TestBuildResponse:
    def test_original_and_links_included(self):
        from src.constants import SERVICES

        data = {
            'url': 'https://open.spotify.com/track/1',
            'original_service': SERVICES['Spotify'],
            'title': 'Title (Remix)',
            'artists': 'A.B',
        }
        links = [
            {'service': '🟠 Yandex Music', 'url': 'https://music.yandex.ru/album/1/track/2'},
            {'service': '🟣 MTS Music', 'url': None},
        ]
        response = build_response(data, links)

        # Спецсимволы MarkdownV2 экранированы
        assert 'A\\.B' in response
        assert '\\(Remix\\)' in response
        # Ссылка без URL не выводится
        assert 'MTS' not in response
        assert 'music.yandex.ru/album/1/track/2' in response

    async def test_fallback_to_plain_on_markdown_error(self):
        """Если Telegram отклонил разметку — отправляем без неё, а не молчим."""
        handlers = BotHandlers()
        update = make_message('https://open.spotify.com/track/123')
        from src.constants import SERVICES

        data = {
            'url': 'https://open.spotify.com/track/123',
            'original_service': SERVICES['Spotify'],
            'title': 'Test',
            'artists': 'Test',
        }

        parsing_msg = AsyncMock()
        # Первый вызов (MarkdownV2) падает как BadRequest, второй — проходит
        parsing_msg.edit_text = AsyncMock(
            side_effect=[Exception('cant parse entities'), None]
        )
        with patch.object(update.message, 'reply_text', new=AsyncMock(return_value=parsing_msg)):
            with patch('src.message_handler.parse_link', new=AsyncMock(return_value=data)):
                with patch('src.message_handler.find_link', new=AsyncMock(return_value=[])):
                    await handlers.handle_message(update, None)

        assert parsing_msg.edit_text.call_count == 2
