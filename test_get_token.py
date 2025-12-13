import sqlite3
import time
import requests
import json

BASE_URL = "https://ads.vk.com/api/v2"
AGENCY_ID = "4MzTOAbEOmZ92WRJ"
AGENCY_SECRET = "3NsAbbjZ3X3AqWvSAWeJ2iiXLKzLknu4OF41CHDcxBHVPiJvNYAvRWhedyQ6a6u6WOjCNTWeoS9JkjhbRyTL1bA1P6rge2T86Ama8IDk24PmIPOecEz5uyz4C13eBapAvgDPT9oMBsRoBC24bJpkwayKrARWdP31mkyDfsHUC6M3lJ5XiYrLZejYSmp7ut9NWJB53b2WBJ4kLusDuQrEON8A91B2t9ooWs5Des7qExSLUG7YyCaWvj"
DB = "tokens.db"




# ------------ Работа с БД ------------
def db():
    return sqlite3.connect(DB)

def get_token_from_db(owner_type, client_id=None):
    conn = db()
    cur = conn.cursor()

    if owner_type == "agency":
        cur.execute("SELECT access_token, refresh_token, expires_at FROM tokens WHERE owner_type='agency'")
    else:
        cur.execute(
            "SELECT access_token, refresh_token, expires_at FROM tokens WHERE owner_type='client' AND client_id=?",
            (client_id,)
        )

    row = cur.fetchone()
    conn.close()
    return row if row else (None, None, None)


def save_token_to_db(owner_type, access_token, refresh_token, expires_at, client_id=None):
    conn = db()
    cur = conn.cursor()

    if owner_type == "agency":
        cur.execute(
            "UPDATE tokens SET access_token=?, refresh_token=?, expires_at=? WHERE owner_type='agency'",
            (access_token, refresh_token, expires_at)
        )
    else:
        cur.execute(
            "UPDATE tokens SET access_token=?, refresh_token=?, expires_at=? WHERE owner_type='client' AND client_id=?",
            (access_token, refresh_token, expires_at, client_id)
        )

    conn.commit()
    conn.close()


def get_agency_token():
    access_token, refresh_token, expires_at = get_token_from_db("agency")

    if access_token is None:
        raise Exception("❌ В БД отсутствует токен агентства")

    if expires_at and expires_at < time.time():
        print("🔄 Agency token expired — refreshing…")
        return refresh_agency_token(refresh_token)

    return access_token

def get_client_refresh_token():
    """Получаем refresh_token клиента из базы"""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT refresh_token FROM tokens
        WHERE owner_type = 'client'
    """)

    result = cur.fetchone()
    conn.close()

    if result is None:
        raise ValueError("В БД нет refresh_token для клиента!")

    return result[0]


def save_new_client_tokens(access_token, refresh_token, expires_in):
    """Сохраняем новые токены клиента в БД"""
    expires_at = int(time.time()) + expires_in

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        UPDATE tokens
        SET access_token = ?, refresh_token = ?, expires_at = ?
        WHERE owner_type = 'client'
    """, (access_token, refresh_token, expires_at))

    conn.commit()
    conn.close()

# ------------ Работа с токеном ------------
def refresh_client_token():
    """Обновляем токен клиента через VK Ads API"""
    refresh_token = get_client_refresh_token()

    url = f"{BASE_URL}/oauth2/token.json"

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": AGENCY_ID,
        "client_secret": AGENCY_SECRET,
    }

    response = requests.post(url, data=data)

    if response.status_code != 200:
        print("Ошибка обновления токена:", response.text)
        return None

    r = response.json()
    print("Ответ VK Ads:", r)

    new_access = r.get("access_token")
    new_refresh = r.get("refresh_token")
    expires_in = r.get("expires_in", 86400)

    # сохраняем в БД
    save_new_client_tokens(new_access, new_refresh, expires_in)

    return new_access

def refresh_agency_token(refresh_token):
    """
    Рефрешим токен агентства
    """
    url = f"{BASE_URL}/oauth2/token.json"

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": AGENCY_ID,
        "client_secret": AGENCY_SECRET,
    }

    r = requests.post(url, data=data).json()
    print(r)

    new_token = r["access_token"]
    new_refresh = r.get("refresh_token", refresh_token)
    expires_at = time.time() + r.get("expires_in", 86400)

    save_token_to_db("agency", new_token, new_refresh, expires_at)

    print("✅ Agency token refreshed")
    return new_token



# ------------ Получение списка клиентов и запись в БД ------------
def get_clients():
    """
    Получает список клиентов агентства.
    Если токен протух — обновляет и повторяет запрос.
    Сохраняет client_id в таблицу clients.
    """
    token = get_agency_token()

    url = f"{BASE_URL}/agency/clients.json"
    headers = {"Authorization": f"Bearer {token}", "client_id": AGENCY_ID}

    r = requests.get(url, headers=headers)

    # 401 / 403 → обновить токен
    if r.status_code in (401, 403):
        print("⚠️ Agency token expired — refreshing…")
        token = refresh_agency_token(get_token_from_db("agency")[1])

        headers["Authorization"] = f"Bearer {token}"
        r = requests.get(url, headers=headers)

    data = r.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))

    # Сохранить client_id в базу
    conn = db()
    cur = conn.cursor()
    for client in data.get("items", []):
        cur.execute("INSERT OR IGNORE INTO clients (client_id) VALUES (?)", (client["user"]["id"],))
    conn.commit()
    conn.close()

    print("✅ Клиенты сохранены в БД")

    return data

get_clients()


