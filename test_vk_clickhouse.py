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
    refresh_client_token,
    get_new_client_token
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

def ensure_tables():
    ch = db()

    # 🟦 BANNERS
    ch.execute("""
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

    # 🟩 CAMPAIGNS (AGG)
    ch.execute("""
        CREATE TABLE IF NOT EXISTS all_campaigns (
            client_id String,
            campaign_id String,
            campaign_name String,
            poll_uuid String,
            date DateTime,

            clicks Float64,
            shows Float64,
            spent_without_vat Float64,

            budget_vat Float64,
            collected_forms Float64,
            plan_forms Float64,
            views_count Float64,
            greeting_conversion Float64,
            days_running Float64
        )
        ENGINE = MergeTree
        PARTITION BY toDate(date)
        ORDER BY (client_id, campaign_id, poll_uuid, date)
    """)

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
        timeout=30
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
# CAMPAIGNS
# ===================================================================
def collect_vk_campaigns(client_id, access_token):
    response = vk_request(
        "/campaigns.json",
        access_token,
        params={"client_id": client_id, "limit": 250},
        resource="CAMPAIGN"
    )

    if response == "unauthorized":
        access_token = refresh_client_token(client_id)
        response = vk_request(
            "/campaigns.json",
            access_token,
            params={"client_id": client_id, "limit": 250},
            resource="CAMPAIGN"
        )

    if not response or "items" not in response:
        return []

    campaigns = []
    for c in response["items"]:
        campaigns.append({
            "campaign_id": str(c["id"]),
            "campaign_name": c.get("name", "")
        })

    return campaigns

# ===================================================================
# BANNERS + UUID
# ===================================================================
def collect_banners_uuid(client_id, access_token):
    response = vk_request(
        "/banners.json",
        access_token,
        params={"client_id": client_id, "limit": 250},
        resource="BANNERS"
    )

    if response == "unauthorized":
        access_token = refresh_client_token(client_id)
        response = vk_request(
            "/banners.json",
            access_token,
            params={"client_id": client_id, "limit": 250},
            resource="BANNERS"
        )

    if not response or "items" not in response:
        return []

    result = []

    for b in response["items"]:
        banner_id = str(b.get("id"))
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
        poll_uuid = parse_qs(parsed.query).get("uuid", [None])[0]
        if not poll_uuid:
            continue

        result.append({
            "campaign_id": campaign_id,
            "banner_id": banner_id,
            "poll_uuid": poll_uuid
        })

    return result

# ===================================================================
# BANNERS STATISTICS
# ===================================================================
def collect_vk_banner_metrics(client_id, access_token, banner_ids):
    if not banner_ids:
        return {}

    result = {}
    BATCH_SIZE = 10

    for i in range(0, len(banner_ids), BATCH_SIZE):
        batch = banner_ids[i:i + BATCH_SIZE]

        stats = vk_request(
            "/statistics/banners/summary.json",
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
            bid = str(item.get("id"))
            base = item.get("total", {}).get("base", {})

            result[bid] = {
                "clicks": float(base.get("clicks", 0)),
                "shows": float(base.get("shows", 0)),
                "spent_without_vat": float(base.get("spent", 0))
            }

    return result

# ===================================================================
# MAIN LOGIC
# ===================================================================
def collect_all_campaigns(clients_tokens):
    ensure_tables()
    ch = db()

    polls = {p["poll_uuid"]: p for p in get_poll_status()}
    print("SOC PANEL POLLS:", len(polls))

    raw_rows = []
    campaign_rows = []

    now = datetime.now()

    for client_id, info in clients_tokens.items():
        if info["owner_type"] != "client":
            continue

        print(f"\n▶ CLIENT {client_id}")
        access_token = info["token"]

        campaigns = collect_vk_campaigns(client_id, access_token)
        if not campaigns:
            continue

        campaigns_map = {c["campaign_id"]: c for c in campaigns}

        banners = collect_banners_uuid(client_id, access_token)
        if not banners:
            continue

        banner_ids = [b["banner_id"] for b in banners]

        banner_stats = collect_vk_banner_metrics(
            client_id,
            access_token,
            banner_ids
        )

        campaign_agg = {}

        for b in banners:
            banner_id = b["banner_id"]
            campaign_id = b["campaign_id"]
            poll_uuid = b["poll_uuid"]

            camp = campaigns_map.get(campaign_id)
            if not camp:
                continue

            stats = banner_stats.get(banner_id, {})
            poll = polls.get(poll_uuid, {})

            # 🟦 RAW (BANNERS)
            raw_rows.append([
                str(client_id),
                str(campaign_id),
                camp.get("campaign_name", ""),
                str(banner_id),
                str(poll_uuid),
                now,

                float(stats.get("clicks", 0)),
                float(stats.get("shows", 0)),
                float(stats.get("spent_without_vat", 0))
            ])

            # 🟩 AGG KEY
            key = (client_id, campaign_id, poll_uuid)

            if key not in campaign_agg:
                campaign_agg[key] = {
                    "client_id": str(client_id),
                    "campaign_id": str(campaign_id),
                    "campaign_name": camp.get("campaign_name", ""),
                    "poll_uuid": str(poll_uuid),
                    "date": now,

                    "clicks": 0.0,
                    "shows": 0.0,
                    "spent": 0.0,

                    "budget_vat": float(poll.get("budget_vat_poll", 0)),
                    "collected_forms": float(poll.get("collected_forms", 0)),
                    "plan_forms": float(poll.get("plan_forms", 0)),
                    "transition": float(poll.get("views_count", 0)),
                    "greeting_conversion": float(poll.get("greeting_conversion", 0)),
                    "days_running": float(poll.get("days_running", 0)),
                }

            campaign_agg[key]["clicks"] += float(stats.get("clicks", 0))
            campaign_agg[key]["shows"] += float(stats.get("shows", 0))
            campaign_agg[key]["spent"] += float(stats.get("spent_without_vat", 0))

        # 🟩 FORM CAMPAIGN ROWS
        for v in campaign_agg.values():
            campaign_rows.append([
                v["client_id"],
                v["campaign_id"],
                v["campaign_name"],
                v["poll_uuid"],
                v["date"],

                v["clicks"],
                v["shows"],
                v["spent"],

                v["budget_vat"],
                v["collected_forms"],
                v["plan_forms"],
                v["transition"],
                v["greeting_conversion"],
                v["days_running"],
            ])

    # ===================================================================
    # INSERT
    # ===================================================================
    if raw_rows:
        ch.execute("INSERT INTO all_campaigns_raw VALUES", raw_rows)
        print(f"🟦 RAW inserted: {len(raw_rows)}")

    if campaign_rows:
        ch.execute("INSERT INTO all_campaigns VALUES", campaign_rows)
        print(f"🟩 CAMPAIGNS inserted: {len(campaign_rows)}")

# ===================================================================
# ENTRYPOINT
# ===================================================================
if __name__ == "__main__":
    print("🚀 START")

    clients_tokens = {}
    agency_id = os.getenv("AGENCY_ID")

    agency_token = get_agency_token()

    clients_tokens[agency_id] = {
        "token": agency_token,
        "owner_type": "agency"
    }

    clients_data = get_clients()

    for client in clients_data.get("items", []):
        cid = str(client["user"]["account"]["id"])

        access, refresh, expires_at = get_tokens("client", cid)

        if not access or (expires_at and expires_at < time.time()):
            if refresh:
                access = refresh_client_token(cid)
            else:
                access = get_new_client_token(cid)

        if access:
            clients_tokens[cid] = {
                "token": access,
                "owner_type": "client"
            }

    collect_all_campaigns(clients_tokens)

    print("🏁 DONE")
