"""Vercel serverless webhook: принимает апдейты Telegram и обрабатывает их.

Ключевая особенность serverless — «тёплые» вызовы: процесс живёт дольше
одного HTTP-запроса. Раньше на каждый запрос создавался новый event loop,
а глобальное приложение Telegram оставалось старым — его httpx-клиент был
привязан к уже закрытому loop, и со второго запроса бот падал
«через раз». Теперь loop один на процесс и не закрывается.
"""
import asyncio
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder

from src.message_handler import BotHandlers

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TELEGRAM_TOKEN')
# Секрет из setWebhook: Telegram присылает его в заголовке, всё прочее
# отбрасываем, чтобы эндпоинт не могли дёргать посторонние
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
SECRET_HEADER = 'X-Telegram-Bot-Api-Secret-Token'

_loop = None
_loop_started = threading.Event()
_loop_lock = threading.Lock()
_app = None
_init_lock = asyncio.Lock()


def _get_loop():
    """Единственный event loop процесса, живёт в фоновом потоке-драйвере.

    Vercel вызывает handler из обычных синхронных потоков, поэтому loop
    нельзя взять из контекста — нужен собственный поток, который его крутит.
    """
    global _loop
    if _loop is not None and not _loop.is_closed():
        return _loop
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        loop = asyncio.new_event_loop()
        _loop = loop
        threading.Thread(
            target=loop.run_forever, name='telegram-bot-loop', daemon=True
        ).start()
        # Дожидаемся старта, иначе run_coroutine_threadsafe повиснет
        while not loop.is_running():
            pass
        return loop


async def _ensure_app():
    """Ленивая инициализация приложения Telegram под асинхронным локом."""
    global _app
    if _app is not None and _app._initialized:
        return _app
    async with _init_lock:
        if _app is not None and _app._initialized:
            return _app
        if not TOKEN:
            raise ValueError('TELEGRAM_TOKEN не найден в переменных окружения')
        logger.info('Initializing Telegram application')
        app = ApplicationBuilder().token(TOKEN).build()
        BotHandlers().setup_handlers(app)
        try:
            await app.initialize()
        except Exception:
            # Не фиксируем полудохлое приложение: следующий запрос
            # попробует инициализацию заново (токен могли поправить и т.п.)
            logger.exception('Инициализация приложения не удалась')
            raise
        _app = app
        logger.info('Telegram application initialized')
    return _app


async def _process_update(update_data):
    app = await _ensure_app()
    update = Update.de_json(update_data, app.bot)
    if update is None:
        logger.warning('Update.de_json вернул None')
        return
    logger.info('Processing update %s', update.update_id)
    await app.process_update(update)
    logger.info('Update %s processed', update.update_id)


def _submit_update(update_data):
    """Планирует обработку апдейта на постоянном loop и ждёт результата."""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(_process_update(update_data), loop)
    # 25 c: конвейер ограничен 20 c, остальное — запас на инициализацию
    return future.result(timeout=25)


class handler(BaseHTTPRequestHandler):
    """Обработчик для Vercel serverless function"""

    def do_POST(self):
        if WEBHOOK_SECRET and self.headers.get(SECRET_HEADER) != WEBHOOK_SECRET:
            self._respond(403, {'ok': False, 'error': 'Forbidden'})
            return

        try:
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            update_data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            self._respond(400, {'ok': False, 'error': 'Invalid JSON'})
            return

        try:
            _submit_update(update_data)
        except Exception:
            # Логируем и отвечаем 200: иначе Telegram будет бесконечно
            # повторять проблемный апдейт
            logger.exception('Ошибка обработки апдейта')
            self._respond(200, {'ok': True, 'error': 'processing failed'})
            return

        self._respond(200, {'ok': True})

    def do_GET(self):
        """Health-check"""
        if not TOKEN:
            self._respond(500, {'status': 'error', 'message': 'TELEGRAM_TOKEN not configured'})
        else:
            self._respond(200, {'status': 'ok', 'service': 'telegram-webhook'})

    def _respond(self, status, payload):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, format, *args):
        pass
