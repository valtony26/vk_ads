import requests

BASE_URL = "https://ads.vk.com/api/v2"
AGENCY_ID = "4MzTOAbEOmZ92WRJ"
AGENCY_SECRET = "3NsAbbjZ3X3AqWvSAWeJ2iiXLKzLknu4OF41CHDcxBHVPiJvNYAvRWhedyQ6a6u6WOjCNTWeoS9JkjhbRyTL1bA1P6rge2T86Ama8IDk24PmIPOecEz5uyz4C13eBapAvgDPT9oMBsRoBC24bJpkwayKrARWdP31mkyDfsHUC6M3lJ5XiYrLZejYSmp7ut9NWJB53b2WBJ4kLusDuQrEON8A91B2t9ooWs5Des7qExSLUG7YyCaWvj"
AGENCY_TOKEN = "boxtKzPxJlHC9G3Y2zCKu4rdozLwgkrK1JGEmbH06QYGPkPEsifeNkNWOffGilzQnSROKMxnsUJzHFrIdV0PstP59mdKikJa0w9AOiaSoxDsLTwOgKl2SoEBOkNaYT2gRKMtnZUkXalSPdI5vlLaxlnLJuQ1ncxFGw3JX5lnnmlPfB7SH6OrVz8NuEG531JiW2WeWGf5110e78"
AGENCY_REFRESH_TOKEN = "9JENDG7uTpYzcQz8Z78CNBmWue9OL8H2f2nmLkH5o9s1duPJ12j0yX1XQixWPp6TQEB10v9nQmLs2YI8jjrnPMlQK9eOP1u9HRO583zGjZOaTEoP3eukYQ63Oq1MY3dJge6mR8ouiIndnl8whu3xd4gdGlAsfX1Ka443nENhJU2JKUvGUr7PfHKRHv8PY9QVQVndBT9ezlE2b2VmEGduFhXIBq"

def get_client():
    global AGENCY_TOKEN

    url = f"{BASE_URL}/agency/clients.json"
    headers = {
        "Authorization": f"Bearer {AGENCY_TOKEN}",
        "client_id": AGENCY_ID
    }

    response = requests.get(url, headers=headers)

    print("REQUESTED URL:", response.url)# ← покажет итоговый URL
    print(response.text)


def get_new_client_token():
    url = f"{BASE_URL}/oauth2/token.json"

    headers = {
        "grant_type": "agency_client_credentials",
        "client_id": AGENCY_ID,
        "client_secret": AGENCY_SECRET,
        "agency_client_id": 19119191
    }

def refresh_agency_token():
    url = f"{BASE_URL}/oauth2/token.json"

    data = {
        "grant_type": "refresh_token",
        "refresh_token": AGENCY_REFRESH_TOKEN,
        "client_id": AGENCY_ID,
        "client_secret": AGENCY_SECRET,
    }

    r = requests.post(url, data=data).json()
    print("Ответ refresh agent:", r)

