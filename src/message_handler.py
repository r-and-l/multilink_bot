"""Обработчики апдейтов Telegram: /start, текстовые сообщения, inline-режим."""
import asyncio
import logging
import re

from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from .link_finder import find_link
from .link_parser import parse_link
from .markdown import escape_markdown

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r'https?://[^\s]+')

# Бюджет на парсинг + поиск по всем сервисам; после этого отвечаем ошибкой,
# а не ждём, пока serverless-функцию убьёт таймаут платформы
PIPELINE_TIMEOUT = 20


def build_response(data, links):
    """Собирает MarkdownV2-ответ: артист - название и ссылки на сервисы."""
    response = (
        f"*{escape_markdown(data['artists'])}* \\- {escape_markdown(data['title'])}\n"
    )
    for info in [data] + list(links):
        service_name = (
            info['original_service']['name']
            if 'original_service' in info
            else info['service']
        )
        if info.get('url'):
            response += f'[{escape_markdown(service_name)}]({info["url"]})\n'
    return response


async def parse_and_find(url):
    """Полный конвейер: парсим ссылку и ищем трек в других сервисах."""
    data = await parse_link(url)
    if data is None:
        return None
    if 'error' in data:
        return data
    links = await find_link(data)
    return data, links


class BotHandlers:
    """Обработчики сообщений Telegram-бота"""

    def __init__(self):
        self.welcome_message = (
            'Hello! Send me a music track link from Spotify, Yandex Music, or MTS Music, '
            "and I'll provide you with multi-links to the track on other services."
        )
        self.invalid_message = (
            'Please send a valid music track link from Spotify, Yandex Music, or MTS Music.'
        )
        self.error_message = 'Error parsing the link. Please try again later.'
        self.timeout_message = (
            'Search took too long. Please try again in a moment.'
        )

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        await update.message.reply_text(self.welcome_message)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        text = update.message.text
        match = URL_REGEX.search(text)

        if not match:
            await update.message.reply_text(self.invalid_message)
            return

        url = match.group(0)
        parsing_msg = await update.message.reply_text(
            '🎶 Parsing your link\\.\\.\\.', parse_mode='MarkdownV2'
        )

        try:
            result = await asyncio.wait_for(
                parse_and_find(url), timeout=PIPELINE_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning('Pipeline timeout for url=%s', url)
            await parsing_msg.edit_text(self.timeout_message)
            return
        except Exception:
            logger.exception('Неожиданная ошибка обработки url=%s', url)
            await parsing_msg.edit_text(self.error_message)
            return

        # None — ссылка не опознана как ссылка на музыку
        if result is None:
            await parsing_msg.edit_text(self.invalid_message)
            return

        if isinstance(result, dict) and 'error' in result:
            logger.warning('Ошибка парсинга url=%s: %s', url, result['error'])
            await parsing_msg.edit_text(self.error_message)
            return

        data, links = result
        response = build_response(data, links)
        try:
            await parsing_msg.edit_text(response, parse_mode='MarkdownV2')
        except Exception:
            # Если Telegram не принял разметку, отдаём текстом без неё
            logger.exception('Не удалось отправить MarkdownV2, пробую plain text')
            await parsing_msg.edit_text(response.replace('\\', ''))

    async def inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик inline-запросов"""
        query = update.inline_query.query
        match = URL_REGEX.search(query)

        results = []
        if match:
            try:
                result = await asyncio.wait_for(
                    parse_and_find(match.group(0)), timeout=PIPELINE_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning('Inline pipeline timeout for query=%s', query)
                result = None
            except Exception:
                logger.exception('Ошибка inline-обработки query=%s', query)
                result = None

            if isinstance(result, tuple):
                data, links = result
                response = build_response(data, links)
                results = [
                    InlineQueryResultArticle(
                        id='multilink',
                        title=f"{data['artists']} - {data['title']}",
                        input_message_content=InputTextMessageContent(
                            response, parse_mode='MarkdownV2'
                        ),
                        description='Get multi-links for the track',
                    )
                ]

        # Отвечаем всегда — иначе клиент показывает «бот не отвечает»
        await update.inline_query.answer(results, cache_time=10)

    def setup_handlers(self, application):
        """Регистрирует все хендлеры в приложении"""
        application.add_handler(CommandHandler('start', self.start_command))
        application.add_handler(InlineQueryHandler(self.inline_query))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )


# Для совместимости с main.py
def setup_handlers(application):
    handlers = BotHandlers()
    handlers.setup_handlers(application)
