"""Where a remote job can be done, and where a candidate is.

Location text ("Remote - USA", "Canada (Remote)", "San Francisco, CA, US; Remote, US",
"Europe, USA, Canada") becomes ISO country codes plus region tags (WORLDWIDE, EUROPE,
EMEA, APAC, LATAM, NORTH_AMERICA, ...). A candidate in country C can take a job whose
places include C, WORLDWIDE, or a region containing C. Text that names no place
("Remote", "Distributed") gives an empty list: unspecified.
"""

import re

WORLDWIDE = "WORLDWIDE"

# code: (display name, aliases matched case-insensitively as whole words)
COUNTRIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "US": ("United States", ("united states", "united states of america", "usa", "u.s.a.", "u.s.",
                             "america", "san francisco", "new york", "nyc", "seattle", "austin",
                             "boston", "chicago", "los angeles", "denver", "atlanta", "miami",
                             "mountain view", "palo alto", "sunnyvale", "san jose", "san mateo",
                             "menlo park", "washington, dc", "washington dc", "portland",
                             "philadelphia", "pittsburgh", "salt lake city", "raleigh",
                             "california", "texas", "colorado", "massachusetts", "illinois",
                             "washington state")),
    "CA": ("Canada", ("canada", "toronto", "vancouver", "montreal", "ottawa", "calgary",
                      "waterloo", "edmonton", "ontario", "british columbia", "quebec",
                      "alberta", "nova scotia")),
    "MX": ("Mexico", ("mexico", "méxico", "mexico city", "guadalajara")),
    "BR": ("Brazil", ("brazil", "brasil", "são paulo", "sao paulo", "rio de janeiro")),
    "AR": ("Argentina", ("argentina", "buenos aires")),
    "CO": ("Colombia", ("colombia", "bogota", "bogotá", "medellin", "medellín")),
    "CL": ("Chile", ("chile", "santiago")),
    "PE": ("Peru", ("peru", "lima")),
    "UY": ("Uruguay", ("uruguay", "montevideo")),
    "CR": ("Costa Rica", ("costa rica",)),
    "GB": ("United Kingdom", ("united kingdom", "great britain", "britain", "england",
                              "scotland", "wales", "london", "manchester", "edinburgh",
                              "cambridge, uk", "bristol")),
    "IE": ("Ireland", ("ireland", "republic of ireland", "dublin", "cork")),
    "DE": ("Germany", ("germany", "deutschland", "berlin", "munich", "münchen", "hamburg",
                       "frankfurt", "cologne")),
    "FR": ("France", ("france", "paris", "lyon")),
    "ES": ("Spain", ("spain", "españa", "madrid", "barcelona", "valencia")),
    "PT": ("Portugal", ("portugal", "lisbon", "lisboa", "porto")),
    "NL": ("Netherlands", ("netherlands", "the netherlands", "holland", "amsterdam",
                           "rotterdam")),
    "BE": ("Belgium", ("belgium", "brussels")),
    "IT": ("Italy", ("italy", "milan", "rome")),
    "CH": ("Switzerland", ("switzerland", "zurich", "zürich", "geneva")),
    "AT": ("Austria", ("austria", "vienna")),
    "PL": ("Poland", ("poland", "warsaw", "krakow", "kraków", "wroclaw", "wrocław")),
    "CZ": ("Czechia", ("czech republic", "czechia", "prague")),
    "HU": ("Hungary", ("hungary", "budapest")),
    "RO": ("Romania", ("romania", "bucharest", "cluj")),
    "GR": ("Greece", ("greece", "athens")),
    "SE": ("Sweden", ("sweden", "stockholm")),
    "NO": ("Norway", ("norway", "oslo")),
    "DK": ("Denmark", ("denmark", "copenhagen")),
    "FI": ("Finland", ("finland", "helsinki")),
    "EE": ("Estonia", ("estonia", "tallinn")),
    "LT": ("Lithuania", ("lithuania", "vilnius")),
    "UA": ("Ukraine", ("ukraine", "kyiv", "kiev")),
    "SERBIA": ("Serbia", ("serbia", "belgrade")),
    "TR": ("Turkey", ("turkey", "türkiye", "istanbul")),
    "IL": ("Israel", ("israel", "tel aviv")),
    "AE": ("United Arab Emirates", ("united arab emirates", "uae", "dubai", "abu dhabi")),
    "SA": ("Saudi Arabia", ("saudi arabia", "riyadh")),
    "EG": ("Egypt", ("egypt", "cairo")),
    "NG": ("Nigeria", ("nigeria", "lagos")),
    "KE": ("Kenya", ("kenya", "nairobi")),
    "ZA": ("South Africa", ("south africa", "cape town", "johannesburg")),
    "IN": ("India", ("india", "bengaluru", "bangalore", "pune", "mumbai", "hyderabad",
                     "delhi", "new delhi", "gurugram", "gurgaon", "noida", "chennai",
                     "kolkata", "ahmedabad")),
    "PK": ("Pakistan", ("pakistan", "karachi", "lahore")),
    "BD": ("Bangladesh", ("bangladesh", "dhaka")),
    "SG": ("Singapore", ("singapore",)),
    "MY": ("Malaysia", ("malaysia", "kuala lumpur")),
    "ID": ("Indonesia", ("indonesia", "jakarta")),
    "PH": ("Philippines", ("philippines", "manila")),
    "VN": ("Vietnam", ("vietnam", "viet nam", "ho chi minh", "hanoi")),
    "TH": ("Thailand", ("thailand", "bangkok")),
    "JP": ("Japan", ("japan", "tokyo", "osaka")),
    "KR": ("South Korea", ("south korea", "korea", "seoul")),
    "CN": ("China", ("china", "beijing", "shanghai", "shenzhen")),
    "TW": ("Taiwan", ("taiwan", "taipei")),
    "HK": ("Hong Kong", ("hong kong",)),
    "AU": ("Australia", ("australia", "sydney", "melbourne", "brisbane", "perth")),
    "NZ": ("New Zealand", ("new zealand", "auckland", "wellington")),
}  # fmt: skip

# Abbreviations that are ordinary words in lower case ("us", "in"): matched only as
# written in capitals.
CASE_SENSITIVE: dict[str, str] = {"US": "US", "UK": "GB", "EU": "EUROPE"}

# US state and Canadian province codes after a comma: "Austin, TX", "Toronto, ON".
# "CA" is read as California, the common case on these boards.
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
]  # fmt: skip
CA_PROVINCES = [
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
]  # fmt: skip

REGIONS: dict[str, tuple[str, ...]] = {
    WORLDWIDE: ("worldwide", "anywhere", "global", "globally", "international",
                "work from anywhere", "all countries"),
    "EUROPE": ("europe", "european union", "european"),
    "EMEA": ("emea",),
    "APAC": ("apac", "asia pacific", "asia-pacific", "asia"),
    "LATAM": ("latam", "latin america", "south america", "central america"),
    "NORTH_AMERICA": ("north america",),
    "AMERICAS": ("americas",),
    "MIDDLE_EAST": ("middle east", "mena"),
    "AFRICA": ("africa",),
}  # fmt: skip

_EUROPE = {"GB", "IE", "DE", "FR", "ES", "PT", "NL", "BE", "IT", "CH", "AT", "PL", "CZ", "HU",
           "RO", "GR", "SE", "NO", "DK", "FI", "EE", "LT", "UA", "SERBIA"}  # fmt: skip
_MIDDLE_EAST = {"TR", "IL", "AE", "SA", "EG"}
_AFRICA = {"EG", "NG", "KE", "ZA"}
_APAC = {"IN", "PK", "BD", "SG", "MY", "ID", "PH", "VN", "TH", "JP", "KR", "CN", "TW", "HK",
         "AU", "NZ"}  # fmt: skip
_LATAM = {"MX", "BR", "AR", "CO", "CL", "PE", "UY", "CR"}
_NORTH_AMERICA = {"US", "CA", "MX"}

REGION_MEMBERS: dict[str, set[str]] = {
    "EUROPE": _EUROPE,
    "EMEA": _EUROPE | _MIDDLE_EAST | _AFRICA,
    "APAC": _APAC,
    "LATAM": _LATAM,
    "NORTH_AMERICA": _NORTH_AMERICA,
    "AMERICAS": _NORTH_AMERICA | _LATAM,
    "MIDDLE_EAST": _MIDDLE_EAST,
    "AFRICA": _AFRICA,
}


def _word(alias: str) -> str:
    return rf"(?<![\w]){re.escape(alias)}(?![\w])"


_ALIASES = sorted(
    [(alias, code) for code, (_, aliases) in COUNTRIES.items() for alias in aliases]
    + [(alias, tag) for tag, aliases in REGIONS.items() for alias in aliases],
    key=lambda pair: -len(pair[0]),  # longest first: "south america" before "america"
)
_ALIAS_RE = re.compile("|".join(_word(a) for a, _ in _ALIASES), re.I)
_ALIAS_CODE = {alias.lower(): code for alias, code in _ALIASES}
_CAPS_RE = re.compile("|".join(_word(a) for a in CASE_SENSITIVE))
_STATE_RE = re.compile(r",\s*(" + "|".join(US_STATES + CA_PROVINCES) + r")\b")


def parse_places(text: str | None) -> list[str]:
    """Country codes and region tags named in a location string, in first-seen order."""
    if not text:
        return []
    found: list[str] = []

    def add(code: str) -> None:
        if code not in found:
            found.append(code)

    for match in _ALIAS_RE.finditer(text):
        add(_ALIAS_CODE[match.group(0).lower()])
    for match in _CAPS_RE.finditer(text):
        add(CASE_SENSITIVE[match.group(0)])
    for match in _STATE_RE.finditer(text):
        add("CA" if match.group(1) in CA_PROVINCES else "US")
    # "South America" mentions America, but it isn't the US: drop a US found only via it.
    if "US" in found and not re.search(
        r"(?<!south )(?<!latin )(?<!central )america|united states|usa|u\.s\.|\bUS\b|, [A-Z]{2}\b",
        text,
        re.I,
    ):
        found.remove("US")
    # "Anywhere in EMEA", "global, US only": the specific place is the restriction.
    if WORLDWIDE in found and len(found) > 1:
        found.remove(WORLDWIDE)
    return found


def eligible_places(country: str) -> list[str]:
    """Every place tag that includes a candidate in `country`."""
    tags = [country, WORLDWIDE]
    tags += [region for region, members in REGION_MEMBERS.items() if country in members]
    return tags


def country_code(text: str | None) -> str | None:
    """The first country named in free text ("Pune, India" -> "IN")."""
    for code in parse_places(text):
        if code in COUNTRIES:
            return code
    return None


def country_name(code: str) -> str:
    return COUNTRIES[code][0] if code in COUNTRIES else code


def country_options() -> list[tuple[str, str]]:
    """(code, name) for every known country, sorted by name, for the UI."""
    return sorted(((code, name) for code, (name, _) in COUNTRIES.items()), key=lambda c: c[1])
