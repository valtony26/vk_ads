import os
import asyncio
import aiohttp
import requests
from dotenv import load_dotenv

load_dotenv(r"C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env")


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
    def get_poll_list(self, limit=10, max_total=1000):
        url = f"{self.BASE_URL}/api/poll/list"

        headers = {
            "Authorization": self.session_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://admin.world-survey.com",
            "Referer": "https://admin.world-survey.com/",
            "User-Agent": "Mozilla/5.0"
        }

        all_polls = []
        offset = 0

        while True:
            # 🔒 защита по максимальному количеству
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

            # ✂️ если добавление превысит лимит — обрезаем
            space_left = max_total - len(all_polls)
            all_polls.extend(polls[:space_left])

            offset += limit

        print(f"✅ Итоговое количество опросов: {len(all_polls)}")
        return all_polls

if __name__ == "__main__":
    client = AsyncAPIClient()

    client.login_request()

    polls = client.get_poll_list()

    print(f"Получено опросов: {len(polls)}")