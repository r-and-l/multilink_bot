# Multilink Bot (Python Version)

A Telegram bot that parses music links from Spotify, Yandex Music, and MTS Music,
finds the same track in the other services and replies with multi-links.

## Features

- Parse track links from Spotify, Yandex Music, and MTS Music
- Search the same track in other services (Spotify, Yandex Music)
- Fuzzy track matching: the bot verifies that the found track is really the
  same one (title + artists) before giving a direct link; otherwise it falls
  back to a search link
- Inline mode support
- Deploys as a Vercel serverless function (warm-safe) or runs locally via polling

## Setup

### Local Development

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your tokens
4. Run the bot: `python main.py`

### Run Tests

```
pip install -r requirements.txt -r test_requirements.txt
pytest
```

### Deploy to Vercel

1. **Push your code to GitHub/GitLab/Bitbucket**

2. **Create a project on Vercel**
   - Go to [vercel.com](https://vercel.com), sign in via your Git provider
   - "Add New Project" and select your repository

3. **Configure environment variables**
   - `TELEGRAM_TOKEN` — your Telegram bot token (required)
   - `YANDEX_MUSIC_TOKEN` — Yandex Music token (for parsing/searching Yandex tracks)
   - `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — Spotify app credentials (for Spotify search)
   - `WEBHOOK_SECRET` — secret string checked against the
     `X-Telegram-Bot-Api-Secret-Token` header (recommended)
   - `MTS_VK_TOKEN` is no longer used: VK audio search returned only
     short-lived mp3 stream URLs, so MTS links always point to the MTS search page

4. **Deploy**
   - Vercel picks up the configuration from `vercel.json`
   - The function runs on Python 3.12 (`runtime.txt`), `maxDuration` is 30 s

5. **Set the Telegram webhook**
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://your-project.vercel.app/api/webhook&secret_token=<WEBHOOK_SECRET>
   ```
   - Check webhook status:
     ```
     https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
     ```

**Note:** after each deploy the project URL may change unless you use a custom
domain — update the webhook URL in Telegram accordingly.

## Project Structure

- `src/config/` — `constants.py` with service definitions
- `src/clients.py` — process-cached API clients (Yandex Music, Spotify)
- `src/link_parser.py` — per-service link parsing (title/artist extraction)
- `src/link_finder.py` — cross-service track search
- `src/matching.py` — fuzzy "is it the same track?" verification
- `src/message_handler.py` — Telegram update handlers
- `api/webhook.py` — Vercel serverless webhook endpoint
- `tests/` — pytest suite (run with `pytest`)
