from clickhouse_driver import Client
import time

def load_tokens_to_clickhouse(file_path: str):
    ch = Client(
        host="localhost",
        database="test_parse",
        user="admin",
        password="123qwe"
    )

    now_ts = int(time.time())
    rows = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            client_id, owner_type, access_token, refresh_token, expires_in = line.split(",")

            expires_at = now_ts + int(expires_in)
            version = now_ts

            rows.append((
                owner_type,
                client_id,
                access_token,
                refresh_token,
                expires_at,
                version
            ))

    ch.execute(
        """
        INSERT INTO test_parse.tokens
        (owner_type, client_id, access_token, refresh_token, expires_at, _version)
        VALUES
        """,
        rows
    )

    print(f"Загружено {len(rows)} токенов")

load_tokens_to_clickhouse(r'C:\Users\tochi\Desktop\work_dialog\looger_for_vkads\access_token_client.txt')