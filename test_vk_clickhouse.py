import os
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

import requests
from clickhouse_driver import Client
from dotenv import load_dotenv

from token_manager import (
    get_agency_token,
    get_clients,
    get_tokens,
    refresh_client_token
)
from test_async_soc_panel import get_poll_status

# ===================================================================
# ENV
# ===================================================================
load_dotenv(r"C:\Users\golubovskiyav\Desktop\WORK\looger_for_vk_ads\vk_ads\.env")
BASE_URL = "https://ads.vk.com/api/v2"

# ===================================================================
# CLICKHOUSE
# ===================================================================
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
            poll_uuid String,
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

            banner_uuid String
        )
        ENGINE = MergeTree
        PARTITION BY toDate(date)
        ORDER BY (client_id, campaign_id, poll_uuid, date)
    """)
    print("✅ Таблица all_campaigns готова")

def ensure_raw_table_exists():
    db().execute("""
        CREATE TABLE IF NOT EXISTS all_campaigns_raw (
            client_id String,
            campaign_id String,
            campaign_name String,
            banner_id String,
            poll_uuid String,
            date DateTime,

            clicks Float64,
            shows Float64,
            spent_without_vat Float64
        )
        ENGINE = MergeTree
        PARTITION BY toDate(date)
        ORDER BY (client_id, campaign_id, banner_id, date)
    """)
    print("✅ Таблица all_campaigns_raw готова")

# ===================================================================
# RATE LIMITED VK REQUEST
# ===================================================================
RATE_LIMITS = {
    "STATISTICS": 1.1,
    "CAMPAIGN": 0.35,
    "BANNERS": 1,
    "DEFAULT": 0.3
}
_last_call = defaultdict(float)

def vk_request(path, access_token, params=None, resource="DEFAULT", max_retries=5):
    delay = RATE_LIMITS.get(resource, RATE_LIMITS["DEFAULT"])
    now = time.time()
    delta = delay - (now - _last_call[resource])
    if delta > 0:
        time.sleep(delta)

    response = requests.get(
        BASE_URL + path,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params or {},
        timeout=20
    )

    _last_call[resource] = time.time()

    if response.status_code == 401:
        return "unauthorized"

    if response.status_code == 429:
        if max_retries <= 0:
            return None
        wait = max(int(response.headers.get("Retry-After", 10)), 10)
        time.sleep(wait)
        return vk_request(path, access_token, params, resource, max_retries - 1)

    if response.status_code != 200:
        return None

    return response.json()

# ===================================================================
# CAMPAIGNS + STATISTICS
# ===================================================================
def get_campaigns(client_id, access_token):
    return vk_request(
        "/campaigns.json",
        access_token,
        params={"client_id": client_id},
        resource="CAMPAIGN"
    )

def collect_vk_campaign_metrics(client_id, access_token):
    campaigns = get_campaigns(client_id, access_token)

    if campaigns == "unauthorized":
        access_token = refresh_client_token(client_id)
        campaigns = get_campaigns(client_id, access_token)
        if campaigns == "unauthorized":
            return []

    if not campaigns or "items" not in campaigns:
        return []

    id_to_name = {str(c["id"]): c.get("name", f"Campaign {c['id']}") for c in campaigns["items"]}

    vk_data = []
    campaign_ids = list(id_to_name.keys())
    BATCH_SIZE = 5

    for i in range(0, len(campaign_ids), BATCH_SIZE):
        batch = campaign_ids[i:i + BATCH_SIZE]

        stats = vk_request(
            "/statistics/campaigns/summary.json",
            access_token,
            params={"client_id": client_id, "ids": ",".join(batch)},
            resource="STATISTICS"
        )

        if not stats or "items" not in stats:
            continue

        for item in stats["items"]:
            cid = str(item.get("id"))
            base = item.get("total", {}).get("base", {})

            vk_data.append({
                "campaign_id": cid,
                "campaign_name": id_to_name.get(cid, ""),
                "clicks": float(base.get("clicks", 0)),
                "shows": float(base.get("shows", 0)),
                "spent_without_vat": float(base.get("spent", 0))
            })

    return vk_data

# ===================================================================
# BANNERS UUID
# ===================================================================
def collect_banners_uuid(client_id, access_token):
    banners_data = vk_request(
        "/banners.json",
        access_token,
        params={"client_id": client_id, "limit": 250},
        resource="BANNERS"
    )

    if banners_data == "unauthorized":
        access_token = refresh_client_token(client_id)
        banners_data = vk_request(
            "/banners.json",
            access_token,
            params={"client_id": client_id, "limit": 250},
            resource="BANNERS"
        )

    if not banners_data or "items" not in banners_data:
        return []

    result = []

    for b in banners_data["items"]:
        banner_id = b.get("id")
        campaign_id = str(b.get("campaign_id"))

        banner_detail = vk_request(
            f"/banners/{banner_id}.json",
            access_token,
            params={"fields": "urls"},
            resource="BANNERS"
        )

        if not banner_detail:
            continue

        url = banner_detail.get("urls", {}).get("primary", {}).get("url")
        if not url:
            continue

        parsed = urlparse(url)
        uuid = parse_qs(parsed.query).get("uuid", [None])[0]

        result.append({
            "campaign_id": campaign_id,
            "poll_uuid": uuid or "",
            "banner_id": str(banner_id)
        })

    return result

# ===================================================================
# CLIENT TOKEN SAFE
# ===================================================================
def get_client_token(client_id):
    """Возвращает рабочий токен клиента VK Ads."""
    access, refresh, expires_at = get_tokens("client", client_id)

    if not access:
        raise Exception(f"Нет access_token для клиента {client_id}")

    # Проверяем истечение токена
    if expires_at is None or expires_at < time.time():
        if refresh:
            new_access = refresh_client_token(client_id)
            if new_access:
                access = new_access
            else:
                print(f"⚠️ Не удалось обновить токен для клиента {client_id}, используем старый")
        else:
            print(f"⚠️ Токен клиента {client_id} истёк, но refresh_token отсутствует")
    return access

# ===================================================================
# MAIN LOGIC
# ===================================================================
def collect_all_campaigns(clients_tokens):
    ensure_table_exists()
    ensure_raw_table_exists()

    ch = db()
    poll_data = get_poll_status()
    polls_by_id = {p["poll_id"]: p for p in poll_data}

    raw_rows = []
    filtered_rows = []

    for client_id, info in clients_tokens.items():
        if info["owner_type"] != "client":
            continue

        print(f"\n▶ CLIENT {client_id}")
        access_token = info["token"]

        campaigns = collect_vk_campaign_metrics(client_id, access_token)
        if not campaigns:
            continue

        banner_uuids = collect_banners_uuid(client_id, access_token)
        campaign_banner_map = defaultdict(list)
        for b in banner_uuids:
            campaign_banner_map[b["campaign_id"]].append(b)

        for camp in campaigns:
            campaign_id = camp["campaign_id"]
            banners = campaign_banner_map.get(campaign_id, [])

            for b in banners:
                poll_uuid = b["poll_uuid"]
                banner_id = b["banner_id"]

                # RAW
                raw_rows.append([
                    str(client_id),
                    str(campaign_id),
                    str(camp.get("campaign_name", "")),
                    str(banner_id),
                    str(poll_uuid),
                    datetime.now(),

                    float(camp.get("clicks", 0)),
                    float(camp.get("shows", 0)),
                    float(camp.get("spent_without_vat", 0))
                ])

                # FILTERED
                poll = polls_by_id.get(poll_uuid)
                if not poll:
                    continue

                filtered_rows.append([
                    str(client_id),
                    str(campaign_id),
                    str(camp.get("campaign_name", "")),
                    str(poll_uuid),
                    datetime.now(),

                    float(poll.get("collected_forms", 0)),
                    float(camp.get("clicks", 0)),
                    float(camp.get("shows", 0)),
                    float(camp.get("spent_without_vat", 0)),
                    float(poll.get("plan_forms", 0)),
                    float(poll.get("budget_vat", 0)),
                    float(poll.get("platform_transitions", 0)),
                    float(poll.get("greeting_conversion", 0)),
                    float(poll.get("days_running", 0)),

                    str(banner_id)
                ])

    # Очистка None перед вставкой
    raw_rows = [[col if col is not None else "" for col in row] for row in raw_rows]
    filtered_rows = [[col if col is not None else "" for col in row] for row in filtered_rows]

    if raw_rows:
        ch.execute("INSERT INTO all_campaigns_raw VALUES", raw_rows)
        print(f"\n🟦 RAW вставлено строк: {len(raw_rows)}")

    if filtered_rows:
        ch.execute("INSERT INTO all_campaigns VALUES", filtered_rows)
        print(f"🟩 FILTERED вставлено строк: {len(filtered_rows)}")

# ===================================================================
# ENTRYPOINT
# ===================================================================
if __name__ == "__main__":
    print("🚀 Старт")

    clients_tokens = {}
    agency_id = os.getenv("AGENCY_ID")
    print("AGENCY_ID:", repr(agency_id))

    # Агентский токен
    clients_tokens[agency_id] = {
        "token": get_agency_token(),
        "owner_type": "agency"
    }

    # Токены клиентов
    for client in get_clients().get("items", []):
        cid = str(client["user"]["account"]["id"])
        access, _, _ = get_tokens("client", cid)
        if access:
            clients_tokens[cid] = {
                "token": get_client_token(cid),
                "owner_type": "client"
            }

    collect_all_campaigns(clients_tokens)
    print("🏁 Готово")
