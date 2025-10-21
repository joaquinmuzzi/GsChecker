import requests

nombre = "Frodouwu"
reino = "Lordaeron"

# ID de subcategoría 15041 y 15042 (Fall of the Lich King 10/25)
urls = [
    f"https://armory.warmane.com/api/character/{nombre}/{reino}/achievements/168/15041",
    f"https://armory.warmane.com/api/character/{nombre}/{reino}/achievements/168/15042"
]

headers = {"User-Agent": "Mozilla/5.0"}

for url in urls:
    r = requests.get(url, headers=headers)
    print(url, "→", r.status_code)
    print(r.text[:300])