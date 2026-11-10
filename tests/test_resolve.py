from trg.graph.resolve import CompanyIndex, PersonIndex, PersonRef, legal_form, parse_born, person_key


def test_transliterations_share_a_key():
    assert person_key("VOLKOV, Aleksandr Sergeyevich") == person_key("Alexander Wolkow") == person_key("Aleksandr Volkov")
    assert person_key("Dmitriy Zhukov") == person_key("Dmitri Schukow")
    assert person_key("Mohammed Al-Rashid") == person_key("Muhammad Alrashid") == person_key("Mohamed El Rashid")
    assert person_key("Jürgen Müller") == person_key("Juergen Mueller") == person_key("Müller, Jürgen")
    assert person_key("Zhang Wei") == person_key("Wei Zhang")


def test_birth_dates_decide_between_namesakes():
    idx = PersonIndex()
    idx.add("a", PersonRef("Müller, Jürgen", **parse_born("12.03.1971")))
    assert idx.resolve(PersonRef("MULLER, Jurgen", **parse_born("March 1971")))[0] == "a"
    assert idx.resolve(PersonRef("Jürgen Müller", **parse_born("1952-11-08")))[0] is None  # a namesake
    # a registry that gives no birth date: a name alone does not merge into someone with one
    assert idx.resolve(PersonRef("Müller, Jürgen", nationality="DE"))[0] is None


def test_initials_and_legal_forms():
    idx = PersonIndex()
    idx.add("a", PersonRef("Anna Schmidt", **parse_born("1980-05-01")))
    assert idx.resolve(PersonRef("A. Schmidt", **parse_born("1980-05-01")))[0] == "a"
    assert legal_form("Trident Investments LLC") == "llc" and legal_form("TRIDENT INVESTMENTS LIMITED") == "ltd"
    c = CompanyIndex()
    c.add("ae", "Trident Investments LLC", "AE", None)
    assert c.resolve("Trident Investments Ltd", None, None, "Limassol") is None  # an LLC is not a Ltd
    c.add("cy", "Trident Investments Ltd", "CY", "HE 1", "Limassol")
    assert c.resolve("TRIDENT INVESTMENTS LTD", "CY", "HE 1") == "cy"


def test_someone_known_by_an_initial_is_found_by_full_name():
    idx = PersonIndex()
    idx.add("w", PersonRef("W. Zhou", **parse_born("1962-07-01")))
    assert idx.resolve(PersonRef("ZHOU, Wei", **parse_born("1962-07-01")))[0] == "w"
    assert idx.resolve(PersonRef("ZHOU, Wei", **parse_born("1970-01-01")))[0] is None
