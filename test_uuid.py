import requests
from dotenv import load_dotenv
import time
import os
from token_manager import get_agency_token, get_clients, get_new_client_token, refresh_client_token




load_dotenv(r'C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env')
BASE_URL = "https://ads.vk.com/api/v2"
AGENCY_ID = os.getenv("AGENCY_ID")
AGENCY_SECRET = os.getenv("AGENCY_SECRET")

def vk_request(path, access_token, params=None, retries=3):
    while retries > 0:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(BASE_URL + path, headers=headers, params=params or {})

        if response.status_code == 401:
            return "unauthorized"

        if response.status_code == 429:
            wait_time = int(response.headers.get("Retry-After", 5))
            print(f"Лимит API, ждём {wait_time} сек...")
            time.sleep(wait_time)
            retries -= 1
            continue

        if response.status_code != 200:
            print(f"Ошибка API {response.status_code}: {response.text}")
            return None

        return response.json()
    return None

# --- Получение кампаний ---
def get_campaigns(client_id, access_token):
    data = vk_request("/campaigns.json", access_token, {"client_id": client_id})
    if data == "unauthorized":
        return "unauthorized"
    return data.get("items", []) if data else []


def collect_vk_campaign_metrics(client_id, access_token):
    """
    Собирает статистику рекламных кампаний VK и возвращает список словарей.
    Не выполняет вставку в ClickHouse.
    """
    campaigns = get_campaigns(client_id, access_token)

    # Если токен недействителен — пробуем обновить
    if campaigns == "unauthorized":
        print(f"Токен клиента {client_id} недействителен, обновляем...")
        new_access = refresh_client_token(client_id)
        if not new_access:
            print(f"Не удалось обновить токен клиента {client_id}")
            return []
        access_token = new_access
        campaigns = get_campaigns(client_id, access_token)
        if campaigns == "unauthorized":
            print(f"Новый токен клиента {client_id} тоже недействителен")
            return []

    vk_data = []

    for camp in campaigns or []:
        campaign_id = str(camp["id"])
        campaign_name = camp.get("name", f"Campaign {campaign_id}")

        # Запрашиваем статистику кампании
        stats = vk_request(
            "/statistics/campaigns/summary.json",
            access_token,
            params={"client_id": client_id, "ids": campaign_id}
        )

        if not stats:
            print(f"⚠️ Нет статистики для кампании {campaign_name}")
            continue

        try:
            base = stats["items"][0]["total"]["base"]
        except (IndexError, KeyError):
            continue

        clicks = float(base.get("clicks", 0))
        shows = float(base.get("shows", 0))
        spent_without_vat = float(base.get("spent", 0))

        vk_data.append({
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "clicks": clicks,
            "shows": shows,
            "spent_without_vat": spent_without_vat
        })
    print(vk_data)
    return vk_data

def get_add_plans(agency_token, client_id):
    add_plans = vk_request(
        "/ad_plans.json",
        agency_token,
        params={"client_id": client_id}
    )
    print(add_plans)
    return add_plans

if __name__ == "__main__":
    agency_token = get_agency_token()

    clients_data = get_clients()   # агентский токен внутри
    if not clients_data or "items" not in clients_data:
        raise RuntimeError("❌ Не удалось получить список клиентов")

    for client in clients_data["items"]:
        client_id = str(client["user"]["account"]["id"])

        add_plans = get_add_plans(agency_token, client_id)

        if add_plans == "unauthorized":
            raise RuntimeError("❌ AGENCY TOKEN INVALID")

        if not add_plans or not add_plans.get("items"):
            print(f"ℹ️ У клиента {client_id} нет объявлений")
            continue

        print(f"📢 Клиент {client_id}, объявлений: {len(add_plans['items'])}")

        for ad in add_plans["items"]:
            print({
                "client_id": client_id,
                "ad_id": ad.get("id"),
                "name": ad.get("name"),
                "status": ad.get("status"),
                "campaign_id": ad.get("campaign_id"),
            })
