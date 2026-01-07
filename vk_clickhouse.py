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
    refresh_client_token,
    refresh_agency_token,
    get_tokens
)
from test_async_soc_panel import get_poll_status


# ===================================================================
# ENV
# ===================================================================

load_dotenv(r"C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env")

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
        params=params or {}
    )

    _last_call[resource] = time.time()

    if response.status_code == 401:
        return "unauthorized"

    if response.status_code == 429:
        if max_retries <= 0:
            print(f"❌ 429 {resource}, retries исчерпаны")
            return None

        wait = max(int(response.headers.get("Retry-After", 10)), 10)
        print(f"⏳ 429 {resource}, sleep {wait}s")
        time.sleep(wait)
        return vk_request(path, access_token, params, resource, max_retries - 1)

    if response.status_code != 200:
        print(f"❌ VK API {resource} {response.status_code}: {response.text}")
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

    id_to_name = {
        str(c["id"]): c.get("name", f"Campaign {c['id']}")
        for c in campaigns["items"]
    }

    vk_data = []
    campaign_ids = list(id_to_name.keys())
    BATCH_SIZE = 5

    for i in range(0, len(campaign_ids), BATCH_SIZE):
        batch = campaign_ids[i:i + BATCH_SIZE]

        stats = vk_request(
            "/statistics/campaigns/summary.json",
            access_token,
            params={
                "client_id": client_id,
                "ids": ",".join(batch)
            },
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
        if not uuid:
            continue

        result.append({
            "campaign_id": campaign_id,
            "uuid": uuid
        })

    return result


# ===================================================================
# MAIN LOGIC
# ===================================================================

def collect_all_campaigns(clients_tokens):
    ensure_table_exists()
    ch = db()

    poll_data = get_poll_status()
    polls_by_id = {p["poll_id"]: p for p in poll_data}

    rows = []

    for client_id, info in clients_tokens.items():
        if info["owner_type"] != "client":
            continue

        access_token = info["token"]
        print(f"\n▶ CLIENT {client_id}")

        campaigns = collect_vk_campaign_metrics(client_id, access_token)
        if not campaigns:
            continue

        banner_uuids = collect_banners_uuid(client_id, access_token)
        campaign_uuid_map = defaultdict(set)
        for b in banner_uuids:
            campaign_uuid_map[b["campaign_id"]].add(b["uuid"])

        for camp in campaigns:
            campaign_id = camp["campaign_id"]
            uuids = campaign_uuid_map.get(campaign_id, set())
            if not uuids:
                continue

            for uuid in uuids:
                poll = polls_by_id.get(uuid)
                if not poll:
                    continue

                rows.append([
                    client_id,
                    campaign_id,
                    camp["campaign_name"],
                    uuid,
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

                    uuid
                ])

    cleaned_rows = [
        [col if col is not None else "" for col in row]
        for row in rows
    ]

    if cleaned_rows:
        ch.execute("INSERT INTO all_campaigns VALUES", cleaned_rows)
        print(f"\n✅ Вставлено строк: {len(cleaned_rows)}")


# ===================================================================
# ENTRYPOINT
# ===================================================================

if __name__ == "__main__":
    print("🚀 Старт")

    clients_tokens = {}

    clients_tokens[os.getenv("AGENCY_ID")] = {
        "token": get_agency_token(),
        "owner_type": "agency"
    }

    for client in get_clients().get("items", []):
        cid = str(client["user"]["account"]["id"])
        access, _, _ = get_tokens("client", cid)
        if access:
            clients_tokens[cid] = {
                "token": access,
                "owner_type": "client"
            }

    collect_all_campaigns(clients_tokens)
    print("🏁 Готово")
