import requests

BASE_URL = "https://ads.vk.com/api/v2"
AGENCY_ID = "4MzTOAbEOmZ92WRJ"
AGENCY_SECRET = "3NsAbbjZ3X3AqWvSAWeJ2iiXLKzLknu4OF41CHDcxBHVPiJvNYAvRWhedyQ6a6u6WOjCNTWeoS9JkjhbRyTL1bA1P6rge2T86Ama8IDk24PmIPOecEz5uyz4C13eBapAvgDPT9oMBsRoBC24bJpkwayKrARWdP31mkyDfsHUC6M3lJ5XiYrLZejYSmp7ut9NWJB53b2WBJ4kLusDuQrEON8A91B2t9ooWs5Des7qExSLUG7YyCaWvj"
AGENCY_TOKEN = "yvVCewTSgPhnf2gGtfLb9FKnYUdYYYzScvh1Oa616lFRijI58qzdVFWG70gzyIuCBIYBNaWfIxK7hlqhe7SrXB6oQTaT6HOb6Omue5Hfo1nMXH7Ez1rIro21aZHY1dC78YTO5cHPnJrb9bsd06KzdYrJeT7QF3hXjhh1gISAUTs8A3TryROIxYVLgAGFbotqCyjshN6kRNFUqK52b5xyEW"
AGENCY_REFRESH_TOKEN = "A92gf3IDqTtW5bBvPIShZwpXmQ2wEfmUXy0VTPMlkZApYDxib7K8bQZQTlGACcFnjolzYVcnYJ9AQzGprwsNdbjTm58vutAeSen6dsd4nJ4h9WFNpPaLEYzfT2g5VWwJ03iqYP129UcH1VG1LGwwHYnlfERYX78m5fPCu27IDQf6m86STybyvuJOiSylHgM3kKpUO94t6hllnjgQAPty2TGaXHoNQ"

def get_client():
    global AGENCY_TOKEN

    url = f"{BASE_URL}/agency/clients.json"
    headers = {
        "Authorization": "Bearer ",
        "access_token": AGENCY_TOKEN,
        "client_id": AGENCY_ID
    }

    response = requests.get(url, headers=headers)

    print("REQUESTED URL:", response.url)  # ← покажет итоговый URL


def get_new_client_token():
    url = f"{BASE_URL}/oauth2/token.json"

    headers = {
        "grant_type": "agency_client_credentials",
        "client_id": AGENCY_ID,
        "client_secret": AGENCY_SECRET,
        "agency_client_id":
    }
