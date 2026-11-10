from trg.graph.ask import Asker, dates
from trg.graph.design import Design
from trg.graph.ingest import day


class NoModel:
    def complete(self, req):
        raise AssertionError("the rules should read these")


def asker():
    return Asker(
        None,
        NoModel(),
        Design(),
        {},
        {"u1": ["Nordwind Logistik GmbH", "Nordwind Logistik"], "u2": ["Atlas Trading Ltd"], "u3": ["Atlas Trading AG"]},
        set(),
        0,
    )


def test_dates_in_three_formats():
    assert dates("on 2025-06-30") == [day("2025-06-30")]
    assert dates("am 30.06.2025") == [day("2025-06-30")]
    assert dates("as of 3 May 2023") == [day("2023-05-03")]


def test_intents_in_english_and_german():
    a = asker()
    assert a.parse("Wer war Geschäftsführer der Nordwind Logistik am 04.12.2024?")["intent"] == "directors"
    assert a.parse("Gibt es Sanktionsbezüge bei Nordwind Logistik zum 13.07.2023?")["intent"] == "sanctions_exposure"
    p = a.parse("Who are the beneficial owners of Nordwind Logistik GmbH above 25% as of 2025-01-01?")
    assert p["intent"] == "ubo" and p["c"] == "u1"


def test_same_name_suppliers_need_the_legal_form():
    a = asker()
    assert a.parse("Who owned Atlas Trading AG on 2025-01-01?")["c"] == "u3"
    a.parse("Who owned Atlas Trading on 2025-01-01?")
    assert a.ambiguous
