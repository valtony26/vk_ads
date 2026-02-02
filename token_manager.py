from clickhouse_driver import Client
import time
import requests
import os
from dotenv import load_dotenv

load_dotenv(r'C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\.env')

BASE_URL = "https://ads.vk.com/api/v2"

AGENCY_ID = os.getenv("AGENCY_ID")
AGENCY_SECRET = os.getenv("AGENCY_SECRET")


def db():
    return Client(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME")
    )

# ============================================================
# INIT DB
# ============================================================

def init_db():
    client = db()
    client.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            client_id String,
            owner_type String,
            access_token String,
            refresh_token String,
            expires_at Int64,
            _version UInt64
        )
        ENGINE = ReplacingMergeTree(_version)
        ORDER BY (owner_type, client_id)
    """)

    # Добавляем агентскую строку, если еще нет
    rows = client.execute(f"""
        SELECT count() 
        FROM tokens 
        WHERE owner_type='agency' AND client_id='{AGENCY_ID}'
    """)

    if rows[0][0] == 0:
        client.execute(f"""
            INSERT INTO tokens 
            (client_id, owner_type, access_token, refresh_token, expires_at, _version)
            VALUES ('{AGENCY_ID}','agency',  '', '', 0, {int(time.time())})
        """)


# ============================================================
# TOKEN READ/WRITE
# ============================================================

def get_tokens(owner_type: str, owner_id: str):
    """
    Возвращает токены из ClickHouse.
    Всегда возвращает 4 значения: access_token, refresh_token, expires_at
    """
    client = db()

    rows = client.execute(f"""
        SELECT access_token, refresh_token, expires_at
        FROM tokens
        WHERE owner_type='{owner_type}' AND client_id='{owner_id}'
        ORDER BY _version DESC
        LIMIT 1
    """)

    if not rows:
        return None, None, None

    return rows[0]


def get_client_token(client_id):
    """
    Возвращает рабочий токен клиента VK Ads.
    Если токен истёк и есть refresh_token, обновляет его.
    """
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


# --- Сохранение токенов в ClickHouse ---
def save_tokens(owner_type, client_id, access_token, refresh_token, expires_at):
    """
    Сохраняет токены в ClickHouse.
    """
    ch = db()
    # Подготавливаем данные как список кортежей
    values = [(owner_type, client_id, access_token, refresh_token, expires_at)]

    ch.execute("""
        INSERT INTO tokens (owner_type, client_id, access_token, refresh_token, expires_at)
        VALUES
    """, values)


# ============================================================
# AGENCY TOKEN
# ============================================================

def refresh_agency_token(refresh_token):
    """
    Обновляет токен агентства по refresh_token и сохраняет его в ClickHouse.
    """
    url = f"{BASE_URL}/oauth2/token.json"

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": AGENCY_ID,
        "client_secret": AGENCY_SECRET,
    }

    r = requests.post(url, data=data).json()
    print("Ответ refresh agent:", r)

    if "error" in r:
        raise Exception(f"Ошибка refresh агентства: {r['error']}")

    new_access = r["access_token"]
    new_refresh = r.get("refresh_token", refresh_token)
    expires_at = int(time.time()) + r.get("expires_in", 86400)

    # Сохраняем новые токены в БД
    save_tokens(
        owner_type="agency",
        client_id=AGENCY_ID,
        access_token=new_access,
        refresh_token=new_refresh,
        expires_at=expires_at
    )

    return new_access


def get_agency_token():
    """
    Возвращает действующий токен агентства.
    Если токен истёк, обновляет его и сохраняет в БД.
    """
    access, refresh, expires_at = get_tokens("agency", AGENCY_ID)

    # Если токена нет, пытаемся создать новый через refresh
    if not access:
        if refresh:
            access = refresh_agency_token(refresh)
        else:
            raise Exception("❌ Нет агентских токенов в БД и refresh_token отсутствует")
        return access

    # Проверяем истечение
    if expires_at is None or expires_at < time.time():
        if refresh:
            access = refresh_agency_token(refresh)
        else:
            print(f"⚠️ Агентский токен истёк, но refresh_token отсутствует")
    return access


# ============================================================
# CLIENTS
# ============================================================

def get_clients():
    """
    Получает список клиентов агентства с помощью действующего токена.
    Не обновляет токен дважды.
    """
    token = get_agency_token()  # получаем уже свежий токен

    url = f"{BASE_URL}/agency/clients.json"
    headers = {"Authorization": f"Bearer {token}", "client_id": AGENCY_ID}

    r = requests.get(url, headers=headers)

    if r.status_code in (401, 403):
        raise Exception("❌ Агентский токен неверен или заблокирован при запросе клиентов")

    data = r.json()

    # Добавляем клиентов в таблицу tokens, если их там нет
    client_ch = db()
    for c in data.get("items", []):
        client_id = str(c["user"]["account"]["id"])

        exists = client_ch.execute(f"""
            SELECT count() 
            FROM tokens 
            WHERE owner_type='client' AND client_id='{client_id}'
        """)[0][0]

        if exists == 0:
            client_ch.execute(f"""
                INSERT INTO tokens (
                     client_id, owner_type, access_token, refresh_token, expires_at, _version
                ) VALUES (
                    '{client_id}', 'client', '', '', 0, {int(time.time())}
                )
            """)

    return data


def get_clients_tokens_dict():
    clients_data = get_clients()  # получаем всех клиентов агентства
    clients_tokens = {}

    for client in clients_data.get("items", []):
        client_id = str(client["user"]["account"]["id"])
        access, refresh, expires_at = get_tokens("client", client_id)

        # если токен отсутствует или истёк — получаем новый
        if not access or (expires_at and expires_at < time.time()):
            print(f"Получаем новый токен для клиента {client_id}")
            access = get_new_client_token(client_id)

        if access:
            clients_tokens[client_id] = {
                "token": access,
                "owner_type": "client"
            }
        else:
            print(f"⚠️ Не удалось получить токен для клиента {client_id}")

    return clients_tokens


# ============================================================
# CLIENT WITHOUT TOKEN
# ============================================================

def get_client_without_tokens():
    client = db()
    rows = client.execute("""
        SELECT client_id
        FROM tokens
        WHERE owner_type='client'
          AND (access_token='' OR access_token=' ')
        ORDER BY _version DESC
        LIMIT 1
    """)

    return rows[0][0] if rows else None


def save_client_tokens(client_id, access, refresh, expires_in):
    expires_at = int(time.time()) + expires_in
    save_tokens("client", client_id, access, refresh, expires_at)


# ============================================================
# FIRST CLIENT TOKEN
# ============================================================

def get_new_client_token(client_id):
    url = f"{BASE_URL}/oauth2/token.json"

    data = {
        "grant_type": "agency_client_credentials",
        "client_id": AGENCY_ID,
        "client_secret": AGENCY_SECRET,
        "agency_client_id": client_id
    }

    response = requests.post(url, data=data)

    if response.status_code != 200:
        print("Ошибка получения токена клиента:", response.text)
        return None

    r = response.json()

    if "error" in r:
        print("Ошибка:", r["error"])
        return None

    access = r["access_token"]
    refresh = r.get("refresh_token", "")
    expires_in = r.get("expires_in", 86400)

    save_client_tokens(client_id, access, refresh, expires_in)

    print(f"Токен клиента {client_id} сохранён")
    return access


def refresh_client_token(client_id):
    """
    Обновляет токен клиента по client_id и сохраняет новые токены в ClickHouse.
    """
    # Получаем текущий refresh_token из БД
    access, refresh, expires_at = get_tokens("client", client_id)

    if not refresh:
        print(f"⚠️ Нет refresh-токена для клиента {client_id}")
        return None

    url = f"{BASE_URL}/oauth2/token.json"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": AGENCY_ID,
        "client_secret": AGENCY_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(url, data=data, headers=headers)

    if response.status_code != 200:
        print(f"❌ Ошибка обновления токена клиента {client_id}: {response.text}")
        return None

    r = response.json()
    new_access = r.get("access_token")
    new_refresh = r.get("refresh_token", refresh)
    expires_in = r.get("expires_in", 86400)
    expires_at = int(time.time()) + expires_in

    # Сохраняем новые токены в ClickHouse
    save_tokens(
        owner_type="client",
        client_id=client_id,  # теперь сохраняем по client_id
        access_token=new_access,
        refresh_token=new_refresh,
        expires_at=expires_at
    )

    print(f"✅ Токен клиента {client_id} обновлён и сохранён")
    return new_access




def get_all_tokens():
    """
    Возвращает словарь {client_id: access_token}
    """
    tokens = {}

    clients = get_clients_tokens_dict()
    for client_id in clients:
        token = get_tokens(owner_type="client", owner_id=client_id)
        if token:
            tokens[str(client_id)] = token

    return tokens


