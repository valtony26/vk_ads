import os
from clickhouse_driver import Client
import requests
import time
from datetime import datetime
from dotenv import load_dotenv

from token_manager import get_tokens, refresh_client_token  # импорт функции обновления токена
from test_soc_panel_stat import get_poll_status

load_dotenv(r"C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env")
BASE_URL = "https://ads.vk.com/api/v2"
AGENCY_ID = os.getenv("AGENCY_ID")
AGENCY_SECRET = os.getenv("AGENCY_SECRET")

# --- Подключение к ClickHouse ---
def db():
    return Client(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
    )


# --- Создание таблицы в ClickHouse ---
def ensure_table_exists():
    client = db()
    client.execute("""
        CREATE TABLE IF NOT EXISTS all_campaigns (
    client_id String,
    campaign_id String,
    campaign_name String,
    `Название опроса` String,
    `Дата начала` DateTime,
    `Собрано Анкет` Float64,
    clicks Float64,
    shows Float64,
    `Потрачено в кабинете без НДС` Float64,
    `План по анкетам` Float64,
    `Бюджет на опрос с НДС` Float64,
    `Переходы на платформу` Float64,
    `Конверсия после страницы приветствия` Float64,
    `Длительность сбора (дни)` Float64,
    _version UInt64
)
ENGINE = ReplacingMergeTree(_version)
ORDER BY (client_id, campaign_id);
    """)
    print("✅ Таблица all_campaigns проверена/создана (ClickHouse)")


# --- Расчёт derived-метрик ---
def calc_metrics(clicks, shows, spent):
    spent_with_vat = round(spent * 1.2, 2) if spent else 0
    ecpm_without_vat = (spent_with_vat / shows * 1000) if shows else 0
    ecpc_without_vat = (spent_with_vat / clicks) if clicks else 0
    ctr = (clicks / shows) if shows else 0
    return spent_with_vat, ecpm_without_vat, ecpc_without_vat, ctr


# --- Универсальный запрос к API ---
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


# --- Сбор и запись статистики в ClickHouse с авто-обновлением токена ---
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

    return vk_data


# --- Основная функция для всех клиентов ---
def collect_all_clients(clients_tokens: dict):
    """
    Собирает данные VK и соцпанели для всех клиентов и сохраняет их в ClickHouse.
    """
    ensure_table_exists()

    for client_id, access_token in clients_tokens.items():
        # 1) Сбор данных VK
        vk_data = collect_vk_campaign_metrics(client_id, access_token)

        # Если токен недействителен — пробуем обновить
        if vk_data == "unauthorized" or vk_data is None:
            print(f"Токен клиента {client_id} недействителен, обновляем...")
            new_access = refresh_client_token(client_id)
            if not new_access:
                print(f"Не удалось обновить токен клиента {client_id}")
                continue
            access_token = new_access
            vk_data = collect_vk_campaign_metrics(client_id, access_token)
            if not vk_data or vk_data == "unauthorized":
                print(f"Новый токен клиента {client_id} тоже недействителен")
                continue

        # 2) Получение данных соцпанели
        poll_data = get_poll_status()  # функция возвращает список словарей

        if not poll_data:
            print(f"⚠️ Нет данных соцпанели для клиента {client_id}")
            continue

        # 3) Объединение и вставка в ClickHouse
        client = db()
        rows = []
        for vk_camp, poll in zip(vk_data, poll_data):
            row = [
                str(client_id),
                vk_camp["campaign_id"],
                vk_camp.get("campaign_name", ""),
                poll.get("poll_name", ""),
                datetime.now(),                 # Дата начала
                poll.get("collected_forms", 0),
                vk_camp.get("clicks", 0),
                vk_camp.get("shows", 0),
                vk_camp.get("spent_without_vat", 0),
                poll.get("plan_forms", 0),
                poll.get("budget_vat", 0),
                poll.get("platform_transitions", 0),
                poll.get("greeting_conversion", 0),
                poll.get("days_running", 0),
                int(time.time())                # _version
            ]
            rows.append(row)

        client.execute("""
            INSERT INTO all_campaigns (
                client_id,
                campaign_id,
                campaign_name,
                `Название опроса`,
                `Дата начала`,
                `Собрано Анкет`,
                clicks,
                shows,
                `Потрачено в кабинете без НДС`,
                `План по анкетам`,
                `Бюджет на опрос с НДС`,
                `Переходы на платформу`,
                `Конверсия после страницы приветствия`,
                `Длительность сбора (дни)`,
                _version
            ) VALUES
        """, rows)

        print(f"✅ Данные VK + соцпанели сохранены для клиента {client_id}")
        time.sleep(0.5)

