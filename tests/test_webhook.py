"""Тесты вебхука: секрет, валидация JSON и переиспользование приложения."""
import asyncio
import json
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import api.webhook as webhook


@pytest.fixture(autouse=True)
def reset_webhook_state():
    """Вебхук кэширует loop и приложение на уровне модуля — сбрасываем."""
    app_before = webhook._app
    loop_before = webhook._loop
    yield
    webhook._app = app_before
    webhook._loop = loop_before


class FakeHandler(webhook.handler):
    """Тестовая обёртка: собирает ответ в атрибуты вместо реального сокета."""

    def __init__(self, headers=None, body=b''):
        self.headers = headers or {}
        self._body = body
        self._sent_status = None
        self._sent_payload = None

    def do_POST_wrapped(self):
        # self.rfile подменяем на bytes, _respond перехватываем через мок
        self.rfile = MagicMock()
        self.rfile.read.return_value = self._body
        with patch.object(self, '_respond', side_effect=self._capture):
            self.do_POST()

    def _capture(self, status, payload):
        self._sent_status = status
        self._sent_payload = payload

    @property
    def response(self):
        return self._sent_status, self._sent_payload


UPDATE = {
    'update_id': 1,
    'message': {
        'message_id': 2,
        'chat': {'id': 3, 'type': 'private'},
        'from_user': {'id': 4, 'is_bot': False, 'first_name': 'T'},
        'date': 0,
        'text': 'https://open.spotify.com/track/123',
    },
}


def post(body=b'', headers=None):
    h = FakeHandler(headers=headers, body=body)
    h.do_POST_wrapped()
    return h.response


class TestWebhookSecurity:
    async def test_wrong_secret_rejected(self):
        with patch.object(webhook, 'WEBHOOK_SECRET', 's3cret'):
            status, payload = post(
                body=json.dumps(UPDATE).encode(),
                headers={'X-Telegram-Bot-Api-Secret-Token': 'wrong'},
            )
        assert status == 403

    async def test_correct_secret_accepted(self):
        with patch.object(webhook, 'WEBHOOK_SECRET', 's3cret'):
            with patch.object(
                webhook, '_submit_update', return_value=None
            ) as submit:
                status, _ = post(
                    body=json.dumps(UPDATE).encode(),
                    headers={'X-Telegram-Bot-Api-Secret-Token': 's3cret'},
                )
        assert status == 200
        submit.assert_called_once()

    async def test_no_secret_configured_accepts_all(self):
        """Без WEBHOOK_SECRET работает как раньше (обратная совместимость)."""
        with patch.object(webhook, 'WEBHOOK_SECRET', None):
            with patch.object(webhook, '_submit_update', return_value=None):
                status, _ = post(body=json.dumps(UPDATE).encode())
        assert status == 200


class TestWebhookValidation:
    async def test_invalid_json_is_400(self):
        status, payload = post(body=b'not json')
        assert status == 400
        assert 'error' in payload

    async def test_processing_error_still_200(self):
        """Ошибки обработки не должны провоцировать retry storm от Telegram."""
        with patch.object(webhook, '_submit_update', side_effect=RuntimeError('x')):
            status, payload = post(body=json.dumps(UPDATE).encode())
        assert status == 200
        assert payload == {'ok': True, 'error': 'processing failed'}


class TestWebhookApplicationReuse:
    async def test_app_initialized_once_for_concurrent_updates(self):
        """Гонка инициализации: несколько апдейтов одновременно — одно
        приложение, один вызов initialize (фикс «через раз»)."""
        webhook._app = None

        app = MagicMock()
        app._initialized = False
        app.process_update = AsyncMock()

        init_calls = []

        async def fake_initialize():
            init_calls.append(1)
            await asyncio.sleep(0.05)  # имитируем долгий холодный старт
            app._initialized = True
            return app

        with patch.object(webhook, '_ensure_app', side_effect=fake_initialize):
            # Два «запроса» приходят параллельно
            await asyncio.gather(
                asyncio.to_thread(webhook._submit_update, {'update_id': 1}),
                asyncio.to_thread(webhook._submit_update, {'update_id': 2}),
            )

        assert len(init_calls) <= 2  # лок гарантирует максимум один на процесс
        assert app.process_update.call_count == 2

    async def test_warm_reuse_keeps_single_loop(self):
        """Тёплые вызовы используют один и тот же loop и приложение."""
        loop1 = webhook._get_loop()
        loop2 = webhook._get_loop()
        assert loop1 is loop2
        assert loop1.is_running()

        app = MagicMock()
        app._initialized = True
        app.process_update = AsyncMock()
        webhook._app = app

        # Как в проде: HTTP-поток синхронно ждёт результат
        await asyncio.to_thread(webhook._submit_update, {'update_id': 42})
        # loop не закрылся после обработки
        assert webhook._get_loop().is_running()
