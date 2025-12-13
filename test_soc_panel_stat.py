import requests
import os
import json
from dotenv import load_dotenv

load_dotenv(r'C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env')

class APIClient:
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
    # Авторизация
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
            raise Exception("Не удалось получить session_token")

        print("✅ Авторизация прошла успешно")

    # ------------------------------
    # Автологин
    # ------------------------------
    def ensure_login(self):
        if not self.session_token:
            self.login_request()

    # ------------------------------
    # Универсальный POST
    # ------------------------------
    def post(self, endpoint, data=None):
        self.ensure_login()
        if not endpoint.startswith("/api/"):
            endpoint = f"/api{endpoint}"
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.session_token
        }
        return requests.post(url, json=data or {}, headers=headers, timeout=10)

    # ------------------------------
    # Получить список всех опросов
    # ------------------------------
    def get_poll_list(self):
        response = self.post("/poll/list")
        return response.json().get("result", [])

    # ------------------------------
    # Получить статистику просмотров/стартов/завершений
    # ------------------------------
    def get_poll_stats(self, poll_id, domain_ids=None):
        if domain_ids is None:
            domain_ids = [1]

        payload = {
            "is_poll_complete": True,
            "is_poll_in_progress": True,
            "domain_ids": domain_ids,
            "id": poll_id
        }

        response = self.post("/poll/stat", payload)
        result = response.json().get("result", {})
        return {
            "views_count": result.get("views_count"),
            "started_count": result.get("started_count"),
            "ended_count": result.get("ended_count")
        }

    # ------------------------------
    # Объединённая статистика: формы + просмотры/старты/завершения
    # ------------------------------
    def get_combined_poll_stats(self, domain_ids=None):
        polls = self.get_poll_list()
        print(f"📋 Найдено опросов: {len(polls)}")
        result = []

        for idx, poll in enumerate(polls, start=1):
            poll_id = poll.get("id")
            poll_name = poll.get("name")
            print(f"{idx}/{len(polls)} ⏳ Обрабатываю опрос: {poll_name} (ID {poll_id})")

            # Статистика по формам
            form_stats = {
                "poll_id": poll_id,
                "poll_name": poll_name,
                "collected_forms": sum(c.get("hits", 0) for c in poll.get("counters", [])),
                "plan_forms": sum(c.get("quota", 0) for c in poll.get("counters", [])),
                "platform_transitions": poll.get("platform_transitions", 0),
                "greeting_conversion": poll.get("greeting_conversion", 0),
            }

            # Статистика просмотров/стартов/завершений
            try:
                stats_result = self.get_poll_stats(poll_id=poll_id, domain_ids=domain_ids)
            except Exception as e:
                stats_result = {"views_count": None, "started_count": None, "ended_count": None, "error": str(e)}

            combined = {**form_stats, **stats_result}
            result.append(combined)

            print(
                f"✅ Готово: {poll_name} — views: {combined['views_count']}, started: {combined['started_count']}, ended: {combined['ended_count']}")

        return result

    # ------------------------------
    # Скачать все опросы в JSON файлы
    # ------------------------------
    def download_all_polls(self, save_dir="polls_data"):
        polls = self.get_poll_list()
        os.makedirs(save_dir, exist_ok=True)

        for poll in polls:
            poll_id = poll.get("id")
            poll_name = poll.get("name", f"poll_{poll_id}")

            print(f"Скачиваю опрос: {poll_name} (ID {poll_id})")

            resp = self.post("/poll/get", {"id": poll_id})

            if resp.status_code == 200:
                file_path = f"{save_dir}/{poll_name.replace('/', '_')}_{poll_id}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(resp.json(), f, ensure_ascii=False, indent=4)
                print(f"✅ Сохранено: {file_path}")
            else:
                print(f"Ошибка при скачивании опроса {poll_id}")


# ===================================================================
#                         ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ===================================================================

if __name__ == "__main__":
    client = APIClient()

    # Получить объединённую статистику всех опросов
    all_stats = client.get_combined_poll_stats()
    for s in all_stats:
        print(s)

