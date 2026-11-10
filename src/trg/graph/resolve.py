"""Entity resolution: which mentions in which sources are the same company or person.

Names are normalised (case, accents, umlauts written out, legal forms, word order, patronymics, and the common
ways Russian and Arabic names are transliterated) into a key. A key only proposes candidates. Identifiers decide:
a registry number and country for a company; a date of birth (full, month and year, or year) for a person. A
conflicting identifier rules a candidate out. When the name fits several people and nothing tells them apart,
the mention is not merged: a missed merge costs a duplicate; a false merge puts someone else's sanctions on a
supplier.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

LEGAL = {"gmbh", "ltd", "limited", "llc", "ag", "bv", "b", "v", "as", "a", "s", "co", "inc", "plc", "sa", "fze", "fzco"}
PATRONYMIC = re.compile(r"(ovich|evich|yevich|ovna|evna|yevna|ich)$")
TRANSLIT = [
    ("tsch", "ch"),
    ("sch", "sh"),
    ("shch", "sh"),
    ("zh", "sh"),
    ("kh", "h"),
    ("ts", "s"),
    ("tz", "s"),
    ("z", "s"),
    ("ch", "h"),
    ("ks", "x"),
    ("ph", "f"),
    ("ou", "u"),
    ("ee", "i"),
    ("oo", "u"),
    ("iy", "i"),
    ("yi", "i"),
    ("ij", "i"),
    ("y", "i"),
    ("j", "i"),
    ("w", "v"),
    ("ck", "k"),
    ("dh", "d"),
    ("th", "t"),
    ("q", "k"),
    ("ss", "s"),
    ("ll", "l"),
    ("mm", "m"),
    ("nn", "n"),
    ("tt", "t"),
    ("e", "a"),
    ("o", "a"),
    ("u", "a"),
]
ARTICLE = re.compile(r"^(al|el)(?=[bcdfghklmnpqrstvwxz])")
IOTATED = re.compile(r"^[yj](?=[aeiou])")


def fold(s: str) -> str:
    s = s.replace("ı", "i").replace("İ", "I").replace("ß", "ss")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue")):
        s = s.replace(a, b)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def company_key(name: str) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", fold(name)) if t not in LEGAL]
    return " ".join(toks)


FORMS = [
    ("co ltd", "co-ltd"),
    ("gmbh", "gmbh"),
    ("limited", "ltd"),
    ("ltd", "ltd"),
    ("llc", "llc"),
    ("ag", "ag"),
    ("b v", "bv"),
    ("bv", "bv"),
    ("a s", "as"),
    ("plc", "plc"),
    ("fze", "fze"),
]


def legal_form(name: str) -> str | None:
    """The legal form a name ends with, normalised ('Ltd' and 'Limited' are one form; 'LLC' is another)."""
    s = " ".join(re.findall(r"[a-z0-9]+", fold(name)))
    for raw, norm in FORMS:
        if s.endswith(" " + raw):
            return norm
    return None


def _phon(tok: str) -> str:
    if len(tok) > 5:
        tok = ARTICLE.sub("", tok)
    tok = IOTATED.sub("", tok)
    for a, b in (("ae", "a"), ("oe", "o"), ("ue", "u")):
        tok = tok.replace(a, b)
    for a, b in TRANSLIT:
        tok = tok.replace(a, b)
    tok = re.sub(r"(.)\1+", r"\1", tok)
    return tok[:1] + re.sub(r"[aeiou]", "", tok[1:]) if len(tok) > 3 else tok


def split_person(name: str) -> tuple[list[str], str | None]:
    """Tokens of a person's name (patronymic dropped, 'Family, Given' reordered) and a given-name initial if only
    an initial is written."""
    raw = fold(name)
    if "," in raw:
        fam, giv = raw.split(",", 1)
        raw = f"{giv} {fam}"
    toks = [t for t in re.findall(r"[a-z]+", raw.replace("-", " ")) if t not in {"al", "el"}]
    toks = [t for t in toks if not (PATRONYMIC.search(t) and len(toks) > 2)]
    initial = None
    m = re.match(r"^\s*([a-z])\.\s", raw)
    if m:
        initial = m.group(1)
        toks = [t for t in toks if len(t) > 1]
    return toks, initial


def person_key(name: str, phonetic: bool = True) -> str:
    toks, _ = split_person(name)
    return " ".join(sorted(_phon(t) if phonetic else t for t in toks))


@dataclass
class PersonRef:
    name: str
    dob: str | None = None  # YYYY-MM-DD
    month: str | None = None  # YYYY-MM
    year: str | None = None  # YYYY
    nationality: str | None = None


@dataclass
class Candidate:
    uuid: str
    names: set = field(default_factory=set)
    keys: set = field(default_factory=set)
    dob: str | None = None
    month: str | None = None
    year: str | None = None
    nationality: str | None = None


def parse_born(s: str | None) -> dict:
    """'12.03.1971', '1971-03-12', 'March 1971', '1971' -> the parts we know."""
    if not s:
        return {}
    import datetime as dt

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            d = dt.datetime.strptime(s.strip(), fmt).date()
            return {"dob": d.isoformat(), "month": d.isoformat()[:7], "year": d.isoformat()[:4]}
        except ValueError:
            pass
    try:
        d = dt.datetime.strptime(s.strip(), "%B %Y").date()
        return {"month": d.isoformat()[:7], "year": d.isoformat()[:4]}
    except ValueError:
        pass
    m = re.fullmatch(r"\d{4}", s.strip())
    return {"year": s.strip()} if m else {}


class PersonIndex:
    def __init__(self, phonetic: bool = True, attributes: bool = True):
        self.phonetic, self.attributes = phonetic, attributes
        self.people: dict[str, Candidate] = {}
        self.by_key: dict[str, set[str]] = {}
        self.by_family: dict[str, set[str]] = {}

    def add(self, uid: str, ref: PersonRef) -> None:
        c = self.people.setdefault(uid, Candidate(uid))
        self._absorb(c, ref)

    def _absorb(self, c: Candidate, ref: PersonRef) -> None:
        c.names.add(ref.name)
        k = person_key(ref.name, self.phonetic)
        c.keys.add(k)
        self.by_key.setdefault(k, set()).add(c.uuid)
        toks, _ = split_person(ref.name)
        if toks:
            fam = _phon(toks[-1]) if self.phonetic else toks[-1]
            self.by_family.setdefault(fam, set()).add(c.uuid)
            fam0 = _phon(toks[0]) if self.phonetic else toks[0]
            self.by_family.setdefault(fam0, set()).add(c.uuid)
        for a in ("dob", "month", "year", "nationality"):
            if getattr(ref, a) and not getattr(c, a):
                setattr(c, a, getattr(ref, a))

    def candidates(self, ref: PersonRef) -> list[Candidate]:
        k = person_key(ref.name, self.phonetic)
        toks, initial = split_person(ref.name)
        ids = set(self.by_key.get(k, set()))
        if not self.phonetic:
            return [self.people[i] for i in ids]
        if initial and toks:
            for i in self.by_family.get(_phon(toks[-1]), set()):
                c = self.people[i]
                if any(split_person(n)[0] and split_person(n)[0][0].startswith(initial) for n in c.names):
                    ids.add(i)
        elif len(toks) >= 2:
            # someone we only know by an initial ("W. Zhou"), now named in full
            for fam in (toks[-1], toks[0]):
                for i in self.by_family.get(_phon(fam), set()):
                    c = self.people[i]
                    for n in c.names:
                        rest, ini = split_person(n)
                        if ini and rest and _phon(rest[-1]) == _phon(fam) and any(t.startswith(ini) for t in toks if t != fam):
                            ids.add(i)
        return [self.people[i] for i in ids]

    @staticmethod
    def conflict(c: Candidate, ref: PersonRef) -> bool:
        if c.dob and ref.dob and c.dob != ref.dob:
            return True
        if c.month and ref.month and c.month != ref.month:
            return True
        return bool(c.year and ref.year and c.year != ref.year)

    @staticmethod
    def evidence(c: Candidate, ref: PersonRef) -> int:
        if c.dob and ref.dob:
            return 3
        if c.month and ref.month:
            return 2
        if c.year and ref.year:
            return 1
        return 0

    def resolve(self, ref: PersonRef) -> tuple[str | None, str]:
        """(uuid or None, how): None means 'create a new person'."""
        cands = self.candidates(ref)
        if not self.attributes:
            return (cands[0].uuid, "name") if cands else (None, "new")
        ok = [c for c in cands if not self.conflict(c, ref)]
        if not ok:
            return None, "new" if not cands else "new: identifiers conflict"
        best = max(self.evidence(c, ref) for c in ok)
        top = [c for c in ok if self.evidence(c, ref) == best]
        if len(top) == 1 and best > 0:
            return top[0].uuid, ("dob" if best == 3 else "month" if best == 2 else "year")
        if len(ok) == 1 and best == 0:
            c = ok[0]
            # neither side has a birth date: same name and nationality is all we have, so merge only two such mentions
            if (
                not (c.dob or c.month or c.year)
                and not (ref.dob or ref.month or ref.year)
                and ref.nationality
                and ref.nationality == c.nationality
            ):
                return c.uuid, "name and nationality"
            return None, "new: nothing to tell namesakes apart"
        return None, "new: ambiguous"

    def merge_info(self, uid: str, ref: PersonRef) -> None:
        self._absorb(self.people[uid], ref)


class CompanyIndex:
    def __init__(self, fuzzy: bool = True, attributes: bool = True):
        self.fuzzy, self.attributes = fuzzy, attributes
        self.by_reg: dict[tuple[str, str], str] = {}
        self.by_key: dict[str, list[tuple[str, str | None, str | None, str | None]]] = {}

    def add(self, uid: str, name: str, country: str | None, regno: str | None, city: str | None = None) -> None:
        if regno and country:
            self.by_reg[(country, regno)] = uid
        k = company_key(name) if self.fuzzy else name
        self.by_key.setdefault(k, []).append((uid, country, city, legal_form(name)))

    def resolve(self, name: str, country: str | None = None, regno: str | None = None, city: str | None = None) -> str | None:
        if regno and country and (country, regno) in self.by_reg:
            return self.by_reg[(country, regno)]
        k = company_key(name) if self.fuzzy else name
        hits = self.by_key.get(k, [])
        if not self.attributes:
            return hits[0][0] if hits else None
        form = legal_form(name)
        hits = [h for h in hits if not (form and h[3] and form != h[3])]  # an LLC is not a Ltd
        if regno and country and any(h[1] == country for h in hits):
            return None  # same name, same country, a different registry number: a different company
        same = [h for h in hits if country is None or h[1] == country]
        if city:
            same = [h for h in same if h[2] == city] or [h for h in same if h[2] is None and h[1] == country]
        return same[0][0] if len(same) == 1 else None
