import requests

url = "https://armory.warmane.com/api/character/Frodouwu/Lordaeron/summary"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

response = requests.get(url, headers=headers)

print("Status:", response.status_code)
print("Content-Type:", response.headers.get("Content-Type"))
print("Texto recibido (primeros 200 caracteres):")
print(response.text[:200])
