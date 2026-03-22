import re

ABBREVIATIONS = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "DRIVE": "DR",
    "ROAD": "RD",
    "LANE": "LN",
    "COURT": "CT",
    "CIRCLE": "CIR",
    "PLACE": "PL",
    "TERRACE": "TER",
    "HIGHWAY": "HWY",
    "PARKWAY": "PKWY",
    "SQUARE": "SQ",
    "TRAIL": "TRL",
    "WAY": "WAY",
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
    "APARTMENT": "APT",
    "SUITE": "STE",
    "UNIT": "UNIT",
    "FLOOR": "FL",
    "BUILDING": "BLDG",
    "SAINT": "ST",
}

def normalize_address(address: str) -> str:
    if not address:
        return ""
    
    # Uppercase
    addr = address.upper()
    
    # Eliminar caracteres especiales excepto espacios, números y letras
    addr = re.sub(r'[^\w\s]', ' ', addr)
    
    # Eliminar espacios dobles
    addr = re.sub(r'\s+', ' ', addr).strip()
    
    # Reemplazar abreviaciones
    words = addr.split()
    normalized_words = []
    for word in words:
        normalized_words.append(ABBREVIATIONS.get(word, word))
    
    return ' '.join(normalized_words)

def addresses_match(addr1: str, addr2: str) -> bool:
    return normalize_address(addr1) == normalize_address(addr2)