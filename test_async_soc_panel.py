import os
import asyncio
import aiohttp
import requests
from dotenv import load_dotenv

load_dotenv(r"C:\Users\golubovskiyav\Desktop\WORK\looger_for_vk_ads\vk_ads\.env")


class AsyncAPIClient:
    BASE_URL = os.getenv("BASE_URL")
    LOGIN = os.getenv("LOGIN")
    PASSWORD = os.getenv("PASSWORD")

    def __init__(self):
        self.session_token = None
        self.semaphore = asyncio.Semaphore(5)

    # ------------------------------
    # СИНХРОННЫЙ ЛОГИН
    # ------------------------------
    def login_request(self):
        url = f"{self.BASE_URL}/api/login"
        payload = {"login": self.LOGIN, "password": self.PASSWORD}

        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()

        self.session_token = resp.json()["result"]["session_token"]
        print("✅ Соцпанель: авторизация успешна")

    # ------------------------------
    # СИНХРОННЫЙ СПИСОК ОПРОСОВ
    # ------------------------------
    def get_poll_list(self):
        url = f"{self.BASE_URL}/api/poll/list"
        headers = {"Authorization": self.session_token}
        resp = requests.post(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("result", [])

    # ------------------------------
    # АСИНХРОННАЯ СТАТИСТИКА ОПРОСА
    # ------------------------------
    async def fetch_poll_stat(self, session, poll):
        payload = {
            "is_poll_complete": True,
            "is_poll_in_progress": True,
            "domain_ids": [1],
            "id": poll["id"]
        }

        headers = {
            "Authorization": self.session_token,
            "Content-Type": "application/json"
        }

        async with self.semaphore:
            async with session.post(
                f"{self.BASE_URL}/api/poll/stat",
                json=payload,
                headers=headers
            ) as resp:
                data = await resp.json()
                r = data.get("result", {})

                return {
                    "poll_id": poll["uuid"],
                    "poll_name": poll.get("name", ""),
                    "collected_forms": sum(c.get("hits", 0) for c in poll.get("counters", [])),
                    "plan_forms": sum(c.get("quota", 0) for c in poll.get("counters", [])),
                    "views_count": r.get("views_count", 0),
                    "started_count": r.get("started_count", 0),
                    "ended_count": r.get("ended_count", 0),
                    "platform_transitions": poll.get("platform_transitions", 0),
                    "greeting_conversion": poll.get("greeting_conversion", 0),
                    "budget_vat": poll.get("budget_vat", 0),
                    "days_running": poll.get("days_running", 0),
                }

    # ------------------------------
    # АСИНХРОННЫЙ СБОР ВСЕХ ОПРОСОВ
    # ------------------------------
    async def get_all_poll_stats_async(self):
        polls = self.get_poll_list()
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [self.fetch_poll_stat(session, poll) for poll in polls]
            return await asyncio.gather(*tasks)


# =====================================================================
# СИНХРОННАЯ ФУНКЦИЯ ДЛЯ ИМПОРТА В ДРУГИЕ МОДУЛИ
# =====================================================================
def get_poll_status():
    client = AsyncAPIClient()
    client.login_request()

    try:
        return asyncio.run(client.get_all_poll_stats_async())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(client.get_all_poll_stats_async())
