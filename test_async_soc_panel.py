import os
import json
import asyncio
import aiohttp
import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv(r'C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env')

class AsyncAPIClient:
    # ------------------------------
    # Настройки
    # ------------------------------
    BASE_URL = os.getenv('BASE_URL')
    LOGIN = os.getenv('LOGIN')
    PASSWORD = os.getenv('PASSWORD')

    def __init__(self):
        self.base_url = self.BASE_URL
        self.login = self.LOGIN
        self.password = self.PASSWORD
        self.session_token = None

    # ------------------------------
    # Синхронная авторизация
    # ------------------------------
    def login_request(self):
        url = f"{self.base_url}/api/login"
        headers = {"Content-Type": "application/json"}
        payload = {"login": self.login, "password": self.password}

        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code != 200:
            raise Exception(f"Ошибка авторизации: {response.status_code} {response.text}")

        data = response.json()
        self.session_token = data.get("result", {}).get("session_token")
        if not self.session_token:
            raise Exception("❌ Не удалось получить session_token")

        print("✅ Авторизация прошла успешно")

    # ------------------------------
    # Синхронный список опросов
    # ------------------------------
    def get_poll_list(self):
        url = f"{self.base_url}/api/poll/list"
        headers = {"Content-Type": "application/json", "Authorization": self.session_token}
        response = requests.post(url, headers=headers, timeout=10)
        return response.json().get("result", [])

    # ------------------------------
    # Асинхронная статистика одного опроса
    # ------------------------------
    async def fetch_poll_stats(self, session, poll_id, domain_ids=None):
        if domain_ids is None:
            domain_ids = [1]

        url = f"{self.base_url}/api/poll/stat"
        headers = {"Content-Type": "application/json", "Authorization": self.session_token}
        payload = {
            "is_poll_complete": True,
            "is_poll_in_progress": True,
            "domain_ids": domain_ids,
            "id": poll_id
        }

        async with session.post(url, json=payload, headers=headers, timeout=10) as resp:
            data = await resp.json()
            result = data.get("result", {})
            return {
                "views_count": result.get("views_count"),
                "started_count": result.get("started_count"),
                "ended_count": result.get("ended_count")
            }

    # ------------------------------
    # Асинхронная обработка всех опросов
    # ------------------------------
    async def get_all_poll_stats_async(self, domain_ids=None):
        polls = self.get_poll_list()
        results = []

        async with aiohttp.ClientSession() as session:
            tasks = []

            # Создаем задачи для всех опросов
            for poll in polls:
                poll_id = poll.get("id")
                poll_name = poll.get("name")

                # Статистика по формам
                form_stats = {
                    "poll_id": poll_id,
                    "poll_name": poll_name,
                    "collected_forms": sum(c.get("hits", 0) for c in poll.get("counters", [])),
                    "plan_forms": sum(c.get("quota", 0) for c in poll.get("counters", [])),
                    "platform_transitions": poll.get("platform_transitions", 0),
                    "greeting_conversion": poll.get("greeting_conversion", 0),
                }

                tasks.append((self.fetch_poll_stats(session, poll_id, domain_ids), form_stats))

            # Запускаем все задачи параллельно
            async_tasks = [t[0] for t in tasks]
            responses = await asyncio.gather(*async_tasks, return_exceptions=True)

            # Объединяем статистику
            for idx, stats_result in enumerate(responses):
                form_stats = tasks[idx][1]

                # Если была ошибка
                if isinstance(stats_result, Exception):
                    stats_result = {"views_count": None, "started_count": None, "ended_count": None, "error": str(stats_result)}

                combined = {**form_stats, **stats_result}
                results.append(combined)

        return results


# ===================================================================
#                         ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ===================================================================

if __name__ == "__main__":
    client = AsyncAPIClient()
    client.login_request()  # синхронный логин

    # Асинхронный сбор статистики
    all_stats = asyncio.run(client.get_all_poll_stats_async())

    for s in all_stats:
        print(s)
