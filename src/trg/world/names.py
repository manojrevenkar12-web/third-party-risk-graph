"""Name pools and the ways the same name is written by registries, sanctions lists, newspapers and websites."""

import unicodedata

PEOPLE = {
    "de": {"given": ["Jürgen", "Anna", "Matthias", "Sabine", "Klaus", "Julia", "Stefan", "Katrin", "Uwe", "Lena", "Jörg", "Birgit"],
           "family": ["Müller", "Schmidt", "Weiß", "Groß", "Köhler", "Becker", "Schäfer", "Hoffmann", "Krüger", "Wagner", "Böhm", "Fuchs"],
           "nat": "DE"},
    "ru": {"given": ["Aleksandr", "Dmitriy", "Sergey", "Yuriy", "Mikhail", "Natalya", "Yelena", "Andrey", "Oleg", "Tatyana", "Vladimir", "Yevgeniy"],
           "family": ["Volkov", "Kuznetsov", "Sokolov", "Lebedev", "Zhukov", "Orlov", "Belyayev", "Yakovlev", "Kovalyov", "Semyonov", "Shcherbakov", "Grigoryev"],
           "nat": "RU"},
    "en": {"given": ["Robert", "Sarah", "James", "Emily", "William", "Charlotte", "Thomas", "Olivia", "Richard", "Hannah", "Edward", "Lucy"],
           "family": ["Smith", "Taylor", "Clarke", "Walker", "Wright", "Hughes", "Turner", "Harrison", "Price", "Cooper", "Bennett", "Fletcher"],
           "nat": "GB"},
    "tr": {"given": ["Şükrü", "Ayşe", "Mehmet", "Gülşen", "Çağrı", "Emre", "Özlem", "Murat", "Selçuk", "Zeynep", "Barış", "İlker"],
           "family": ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Öztürk", "Aydın", "Arslan", "Doğan", "Koç", "Kılıç", "Güneş"],
           "nat": "TR"},
    "ar": {"given": ["Mohammed", "Ahmed", "Khalid", "Fatima", "Youssef", "Omar", "Abdullah", "Layla", "Hassan", "Mariam", "Tariq", "Nour"],
           "family": ["Al-Rashid", "Al-Mansouri", "Haddad", "Al-Farsi", "Nasser", "Al-Hashimi", "Khoury", "Al-Qasimi", "Saleh", "Al-Zahrani", "Hamdan", "Al-Amiri"],
           "nat": "AE"},
    "cn": {"given": ["Wei", "Fang", "Jun", "Li", "Hao", "Xiu Ying", "Ming", "Jing", "Lei", "Yan", "Qiang", "Mei"],
           "family": ["Zhang", "Wang", "Li", "Liu", "Chen", "Yang", "Huang", "Zhao", "Wu", "Zhou", "Xu", "Sun"],
           "nat": "CN"},
}
PATRONYMIC = {"Aleksandr": "Aleksandrovich", "Dmitriy": "Dmitriyevich", "Sergey": "Sergeyevich", "Yuriy": "Yuryevich",
              "Mikhail": "Mikhaylovich", "Andrey": "Andreyevich", "Oleg": "Olegovich", "Vladimir": "Vladimirovich"}

# Russian names as German newspapers and registries transliterate them
RU_TO_DE = {"Aleksandr": "Alexander", "Dmitriy": "Dmitri", "Sergey": "Sergej", "Yuriy": "Juri", "Mikhail": "Michail",
            "Natalya": "Natalja", "Yelena": "Jelena", "Andrey": "Andrej", "Oleg": "Oleg", "Tatyana": "Tatjana",
            "Vladimir": "Wladimir", "Yevgeniy": "Jewgeni", "Volkov": "Wolkow", "Kuznetsov": "Kusnezow",
            "Sokolov": "Sokolow", "Lebedev": "Lebedew", "Zhukov": "Schukow", "Orlov": "Orlow", "Belyayev": "Beljajew",
            "Yakovlev": "Jakowlew", "Kovalyov": "Kowaljow", "Semyonov": "Semjonow", "Shcherbakov": "Schtscherbakow",
            "Grigoryev": "Grigorjew"}
AR_VARIANTS = {"Mohammed": ["Muhammad", "Mohamed"], "Ahmed": ["Ahmad"], "Youssef": ["Yusuf", "Youssif"],
               "Abdullah": ["Abdallah"], "Hassan": ["Hasan"], "Tariq": ["Tarek"], "Al-Rashid": ["Alrashid", "El Rashid"],
               "Al-Mansouri": ["Almansouri", "Al Mansoori"], "Al-Farsi": ["Alfarsi"], "Al-Hashimi": ["Al Hashemi"],
               "Al-Qasimi": ["Al Qassimi"], "Al-Zahrani": ["Alzahrani"], "Al-Amiri": ["Al Ameri"]}

STEMS = ["Nordwind", "Baltic Star", "Kestrel", "Falcon Crest", "Atlas", "Meridian", "Helios", "Granite", "Bluewater",
         "Silverline", "Aurora", "Northgate", "Pinnacle", "Rheintal", "Elbe", "Harbourview", "Crescent", "Orion",
         "Sapphire", "Westbrook", "Lindenhof", "Seefeld", "Corvus", "Vega", "Trident", "Highmoor", "Alder", "Eastwind",
         "Goldcrest", "Ironbridge", "Kingfisher", "Larch", "Marlin", "Nimbus", "Oakridge", "Polaris", "Quarry Hill",
         "Redstone", "Sterling", "Tamarind", "Umber", "Valiant", "Wrenfield", "Zephyr", "Ashford", "Brightwater",
         "Cobalt", "Driftwood", "Emberly", "Foxglove"]
SECTORS = {"DE": ["Logistik", "Maschinenbau", "Handel", "Elektronik", "Verpackung", "Chemie"],
           "GB": ["Logistics", "Engineering", "Trading", "Components", "Packaging", "Chemicals"],
           "NL": ["Logistics", "Trading", "Components", "Shipping"],
           "CH": ["Trading", "Commodities", "Engineering"],
           "CY": ["Holdings", "Investments", "Shipping"], "AE": ["Holdings", "General Trading", "Investments"],
           "VG": ["Holdings", "Capital", "Investments"], "TR": ["Lojistik", "Ticaret"], "CN": ["Trading", "Manufacturing"]}
FORMS = {"DE": "GmbH", "GB": "Ltd", "NL": "B.V.", "CH": "AG", "CY": "Ltd", "AE": "LLC", "VG": "Ltd", "TR": "A.Ş.",
         "CN": "Co., Ltd."}
CITY = {"DE": ["Hamburg", "Bremen", "Frankfurt am Main", "Stuttgart", "Leipzig"], "GB": ["London", "Manchester", "Leeds"],
        "NL": ["Rotterdam", "Amsterdam"], "CH": ["Zug", "Geneva", "Lugano"], "CY": ["Limassol", "Nicosia"],
        "AE": ["Dubai", "Sharjah"], "VG": ["Road Town"], "TR": ["Istanbul", "Izmir"], "CN": ["Shenzhen", "Ningbo"]}
COUNTRY = {"DE": "Germany", "GB": "United Kingdom", "NL": "the Netherlands", "CH": "Switzerland", "CY": "Cyprus",
           "AE": "the United Arab Emirates", "VG": "the British Virgin Islands", "TR": "Turkey", "CN": "China",
           "RU": "Russia"}
COUNTRY_DE = {"DE": "Deutschland", "GB": "Großbritannien", "NL": "den Niederlanden", "CH": "der Schweiz", "CY": "Zypern",
              "AE": "den Vereinigten Arabischen Emiraten", "VG": "den Britischen Jungferninseln", "TR": "der Türkei",
              "CN": "China", "RU": "Russland"}


def ascii_fold(s: str) -> str:
    """Müller -> Muller (as many systems store it); umlauts written out are a separate variant."""
    s = s.replace("ı", "i").replace("İ", "I").replace("ß", "ss")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def umlaut_out(s: str) -> str:
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def person_variants(p: dict, r) -> list[str]:
    """The ways this person's name appears in sources, most formal first."""
    g, f, c = p["given"], p["family"], p["culture"]
    out = [f"{g} {f}"]
    if c == "ru":
        pat = p.get("patronymic")
        if pat:
            out.append(f"{g} {pat} {f}")
        out.append(f"{RU_TO_DE.get(g, g)} {RU_TO_DE.get(f, f)}")
        out.append(f"{g.replace('iy', 'y').replace('Ye', 'E')} {f.replace('yev', 'ev').replace('yo', 'e')}")
    elif c == "de":
        out += [umlaut_out(f"{g} {f}"), ascii_fold(f"{g} {f}")]
    elif c == "tr":
        out += [ascii_fold(f"{g} {f}")]
    elif c == "ar":
        for v in AR_VARIANTS.get(g, [])[:1]:
            out.append(f"{v} {f}")
        for v in AR_VARIANTS.get(f, [])[:1]:
            out.append(f"{g} {v}")
    elif c == "cn":
        out.append(f"{f} {g}")  # family name first
    return list(dict.fromkeys(out))
