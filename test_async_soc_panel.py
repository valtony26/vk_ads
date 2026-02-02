import os
import asyncio
import aiohttp
import requests
from dotenv import load_dotenv

# ======================================================
# ЗАГРУЗКА ENV
# ======================================================
load_dotenv(r"C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env")


# ======================================================
# КОНФИГ СЕРВИСОВ
# ======================================================
SERVICES = [
    {
        "name": "world-survey",
        "base_url": os.getenv("BASE_URL"),
        "login": os.getenv("LOGIN"),
        "password": os.getenv("PASSWORD"),
    },
    {
        "name": "online-sociology",
        "base_url": os.getenv("BASE_URL_SOC"),
        "login": os.getenv("LOGIN"),
        "password": os.getenv("PASSWORD_SOC"),
    },
]


# ======================================================
# API CLIENT
# ======================================================
class AsyncAPIClient:
    def __init__(self, base_url, login, password):
        self.BASE_URL = base_url
        self.LOGIN = login
        self.PASSWORD = password

        self.session_token = None
        self.semaphore = asyncio.Semaphore(5)

    # ------------------------------
    # СИНХРОННЫЙ ЛОГИН
    # ------------------------------
    def login_request(self):
        url = f"{self.BASE_URL}/api/login"
        payload = {
            "login": self.LOGIN,
            "password": self.PASSWORD
        }

        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()

        self.session_token = resp.json()["result"]["session_token"]
        print(f"✅ {self.BASE_URL}: авторизация успешна")

    # ------------------------------
    # СИНХРОННЫЙ СПИСОК ОПРОСОВ
    # ------------------------------
    def get_poll_list(self, limit=10, max_total=2000):
        url = f"{self.BASE_URL}/api/poll/list"

        headers = {
            "Authorization": self.session_token,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        all_polls = []
        offset = 0

        while True:
            if len(all_polls) >= max_total:
                print(f"⛔ Достигнут лимит {max_total} опросов")
                break

            payload = {
                "is_in_track": False,
                "limit": limit,
                "offset": offset
            }

            print(f"➡️ offset={offset}")

            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            resp.raise_for_status()

            polls = resp.json().get("result", [])
            print(f"SOC PANEL: получено {len(polls)} опросов")

            if not polls:
                print("⛔ Пустой результат — завершаем пагинацию")
                break

            for p in polls:
                print("  - UUID:", p["uuid"])

            space_left = max_total - len(all_polls)
            all_polls.extend(polls[:space_left])

            offset += limit

        print(f"✅ Итоговое количество опросов: {len(all_polls)}")
        return all_polls

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

                r = data.get("result")
                if not isinstance(r, dict):
                    r = {}

                counters = poll.get("counters") or []

                return {
                    "poll_uuid": poll["uuid"],
                    "poll_name": poll.get("name", ""),

                    "collected_forms": sum(c.get("hits", 0) for c in counters),
                    "plan_forms": sum(c.get("quota", 0) for c in counters),

                    "transition": r.get("views_count", 0),
                    "started_count": r.get("started_count", 0),
                    "ended_count": r.get("ended_count", 0),

                    "greeting_conversion": poll.get("greeting_conversion", 0),
                    "budget_vat_poll": poll.get("budget_vat", 0),
                    "days_running": poll.get("days_running", 0),
                }

    # ------------------------------
    # АСИНХРОННЫЙ СБОР ВСЕХ ОПРОСОВ
    # ------------------------------
    async def get_all_poll_stats_async(self):
        polls = self.get_poll_list()
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [
                self.fetch_poll_stat(session, poll)
                for poll in polls
            ]
            return await asyncio.gather(*tasks)


# ======================================================
# ТОЧКА ВХОДА ДЛЯ ИМПОРТА
# ======================================================
def get_poll_status():
    all_results = []

    for service in SERVICES:
        print(f"\n🚀 Запуск сервиса: {service['name']}")

        client = AsyncAPIClient(
            base_url=service["base_url"],
            login=service["login"],
            password=service["password"],
        )

        client.login_request()

        try:
            results = asyncio.run(client.get_all_poll_stats_async())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            results = loop.run_until_complete(client.get_all_poll_stats_async())

        for r in results:
            r["service"] = service["name"]

        all_results.extend(results)

    return all_results
