#!/usr/bin/env python3
"""
BuySellVouchers watcher ― шлёт оповещения о новых товарах в Telegram.

• Python 3.11+         • playwright ≥1.44
• Запуск:  python monitor.py
  или     docker compose up -d          (см. docker-compose.yml)

Автор: your-name, 2025
"""
from __future__ import annotations

import asyncio, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from telegram import Bot
from dotenv import load_dotenv

# ─── Конфиг ──────────────────────────────────────────────────────────────────
load_dotenv()                                         # подтягиваем переменные из .env
URLS: list[str]      = [
    # примеры продавцов ― замените на свои
    "https://www.buysellvouchers.com/en/seller/info/weiguoliu777/",
]
CHECK_EVERY_SECONDS  = 5 * 60                        # 5 минут
DATA_FILE            = Path("seen_products.json")
TELEGRAM_TOKEN       = os.getenv("TG_TOKEN")
TELEGRAM_CHAT_ID     = int(os.getenv("TG_CHAT_ID", "0"))
HEADLESS             = True                          # False = видно браузер (debug)
# ─────────────────────────────────────────────────────────────────────────────

if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
    sys.exit("❌  TG_TOKEN / TG_CHAT_ID не заданы (см. .env)")

_re_spaces = re.compile(r"\s+")


def fmt(text: str) -> str:
    """Убираем лишние пробелы/переносы."""
    return _re_spaces.sub(" ", text).strip()


async def fetch_products(play, url: str) -> list[dict]:
    """Возвращает список товаров (dict) со страницы продавца."""
    browser   = await play.chromium.launch(headless=HEADLESS)
    context   = await browser.new_context()
    page      = await context.new_page()
    products  = []
    try:
        await page.goto(url, timeout=45_000)
        await page.wait_for_selector("table >> tbody >> tr", timeout=45_000)

        for row in await page.query_selector_all("table >> tbody >> tr"):
            cells = await row.query_selector_all("td")
            if len(cells) < 5:
                continue
            name       = fmt(await cells[0].inner_text())
            price      = fmt(await cells[2].inner_text())
            available  = fmt(await cells[4].inner_text())
            key        = f"{name}|{price}"

            products.append(
                {
                    "key": key,
                    "name": name,
                    "price": price,
                    "available": available,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
    finally:
        await browser.close()
    return products


async def notify(bot: Bot, text: str):
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")


async def check_once(play, bot: Bot):
    seen: set[str] = set(json.loads(DATA_FILE.read_text())) if DATA_FILE.exists() else set()
    new_seen       = set(seen)

    for url in URLS:
        try:
            products = await fetch_products(play, url)
        except PlaywrightTimeout:
            await notify(bot, f"⚠️ Таймаут при загрузке {url}")
            continue

        added = [p for p in products if p["key"] not in seen]
        if added:
            lines = [f"<b>Новый товар у продавца</b>\n{url}"]
            for p in added:
                lines.append(f"• {p['name']} — {p['price']} (доступно: {p['available']})")
                new_seen.add(p["key"])
            await notify(bot, "\n".join(lines))

    DATA_FILE.write_text(json.dumps(sorted(new_seen)))


async def main():
    bot       = Bot(TELEGRAM_TOKEN)
    scheduler = AsyncIOScheduler()
    play      = await async_playwright().start()

    scheduler.add_job(
        check_once, "interval", seconds=CHECK_EVERY_SECONDS, kwargs={"play": play, "bot": bot}
    )
    scheduler.start()

    print("🟢  Monitor started ― Ctrl-C to stop")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await play.stop()


if __name__ == "__main__":
    asyncio.run(main())
