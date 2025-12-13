from token_manager import (
    init_db,
    get_clients_tokens_dict,
    get_client_without_tokens,
    get_new_client_token
)
from test_get_stat import collect_all_clients


if __name__ == "__main__":
    # 1️⃣ Создаем БД и таблицу tokens в ClickHouse
    print("Инициализация ClickHouse…")
    init_db()

    # 2️⃣ Получаем словарь всех клиентов, у которых есть токены
    print("Получаем список клиентов агентства…")
    clients_tokens = get_clients_tokens_dict()

    # 3️⃣ Проверяем — есть ли клиенты без токенов
    while True:
        client_id = get_client_without_tokens()
        if client_id:
            print(f"Найден новый клиент без токена → client_id={client_id}")

            # Попытка получить первый токен
            access_token = get_new_client_token(client_id)

            if access_token:
                clients_tokens[client_id] = access_token
                print(f"Добавлен токен для клиента {client_id}")
            else:
                print(f"❌ Не удалось получить токен для клиента {client_id}")
                break
        else:
            break

    # 4️⃣ Если токенов нет — прекращаем работу
    if not clients_tokens:
        print("❌ Нет доступных токенов клиентов — статистика не будет собрана")
    else:
        # 5️⃣ Собираем статистику по всем клиентам (и пишем в ClickHouse)
        print("Собираем статистику и сохраняем в ClickHouse…")
        collect_all_clients(clients_tokens)
        print("✅ Работа завершена")
