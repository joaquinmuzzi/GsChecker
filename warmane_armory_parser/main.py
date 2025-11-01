import json
from armory_parser import parse_character

character = "Frodouwu"
realm = "Lordaeron"

data = parse_character(character, realm)
print(json.dumps(json.loads(data.to_json()), indent=4))
with open("mi_archivo.json", "w") as archivo:
    archivo.write(data.to_json())