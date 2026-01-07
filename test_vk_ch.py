import os
import time
from datetime import datetime
from clickhouse_driver import Client
from dotenv import load_dotenv

from token_manager import refresh_client_token, get_all_tokens
from test_async_soc_panel import get_poll_status
from test_get_stat import collect_vk_campaign_metrics

load_dotenv(r"C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env")


# ------------------------------ CLICKHOUSE ------------------------------

def db():
    return Client(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
    )


def ensure_table_exists():
    db().execute("""
        CREATE TABLE IF NOT EXISTS all_campaigns (
            client_id String,
            campaign_id String,
            campaign_name String,
            poll_name String,
            date DateTime,

            collected_forms Float64,
            clicks Float64,
            shows Float64,
            spent_without_vat Float64,
            plan_forms Float64,
            budget_vat Float64,
            platform_transitions Float64,
            greeting_conversion Float64,
            days_running Float64,

            _version UInt64
        )
        ENGINE = ReplacingMergeTree(_version)
        ORDER BY (client_id, campaign_id)
    """)
    print("✅ Таблица all_campaigns проверена / создана")


# ------------------------------ MAIN LOGIC ------------------------------

def collect_all_clients(clients_tokens: dict):
    ensure_table_exists()
    ch = db()

    print("⏳ Получаем данные соцпанели...")
    poll_data = get_poll_status() or []

    for client_id, access_token in clients_tokens.items():
        print(f"\n▶ Клиент {client_id}")

        vk_data = collect_vk_campaign_metrics(client_id, access_token)

        if vk_data == "unauthorized":
            print("♻️ Обновляю VK токен...")
            access_token = refresh_client_token(client_id)
            if not access_token:
                print("❌ Не удалось обновить токен")
                vk_data = []
            else:
                vk_data = collect_vk_campaign_metrics(client_id, access_token)

        if not vk_data:
            vk_data = []

        rows = []

        # Вставляем данные VK + дефолты соцпанели
        for camp in vk_data:
            rows.append([
                str(client_id),
                camp.get("campaign_id", ""),
                camp.get("campaign_name", ""),
                "",  # poll_name дефолт
                datetime.now(),
                0,  # collected_forms дефолт
                camp.get("clicks", 0),
                camp.get("shows", 0),
                camp.get("spent_without_vat", 0),
                0,  # plan_forms дефолт
                0,  # budget_vat дефолт
                0,  # platform_transitions дефолт
                0,  # greeting_conversion дефолт
                0,  # days_running дефолт
                int(time.time())
            ])

        # Вставляем данные соцпанели + дефолты VK
        for poll in poll_data:
            rows.append([
                str(client_id),
                "",  # campaign_id дефолт
                "",  # campaign_name дефолт
                poll.get("poll_name", ""),
                datetime.now(),
                poll.get("collected_forms", 0),
                0,  # clicks дефолт
                0,  # shows дефолт
                0,  # spent_without_vat дефолт
                poll.get("plan_forms", 0),
                poll.get("budget_vat", 0),
                poll.get("platform_transitions", 0),
                poll.get("greeting_conversion", 0),
                poll.get("days_running", 0),
                int(time.time())
            ])

        if rows:
            ch.execute("INSERT INTO all_campaigns VALUES", rows)
            print(f"✅ Сохранено строк: {len(rows)}")
        else:
            print("⚠️ Нет строк для вставки")

        time.sleep(0.3)  # защита от API-лимитов


# ------------------------------ ENTRYPOINT ------------------------------

if __name__ == "__main__":
    print("🚀 Запуск сбора данных")

    clients_tokens = get_all_tokens()
    if not clients_tokens:
        print("❌ Не найдено VK токенов")
    else:
        collect_all_clients(clients_tokens)

    print("🏁 Готово")
