from translator.models import extract_variables


def test_mission_call_with_pipe_args():
    assert extract_variables("~mission(Location|Address)") == [
        "~mission(Location|Address)"
    ]


def test_hash_mission_call():
    assert extract_variables("#~mission(Item1|SerialNumber)") == [
        "#~mission(Item1|SerialNumber)"
    ]


def test_mission_call_with_space_before_paren():
    assert extract_variables("~mission (description)") == ["~mission (description)"]


def test_ui_label():
    assert extract_variables("@ui_SomeLabel") == ["@ui_SomeLabel"]


def test_printf_style_placeholders():
    assert extract_variables("%ls %s %S %i %d %u %im %ih") == [
        "%ls",
        "%s",
        "%S",
        "%i",
        "%d",
        "%u",
        "%im",
        "%ih",
    ]


def test_currency_and_unit():
    assert extract_variables("Delivery of 500 SCU and 1000 aUEC required.") == [
        "SCU",
        "aUEC",
    ]


def test_currency_not_matched_without_word_boundary():
    assert extract_variables("This costs 500aUEC total.") == []


def test_unit_inside_longer_identifier_not_split():
    # SCU should not be pulled out separately from a larger ~mission(...) call
    assert extract_variables("~mission(MissionMaxSCUSize)") == [
        "~mission(MissionMaxSCUSize)"
    ]


def test_positional_and_escape_and_tag():
    assert extract_variables("{0} \\n <EM4>") == ["{0}", "\\n", "<EM4>"]


def test_tag_does_not_swallow_surrounding_prose():
    # Regression: a stray '<' delimiter followed by a paragraph and a real
    # tag like <EM4> must not be captured as one giant "variable".
    value = "<\nSome long paragraph of prose with a <EM4>"
    assert extract_variables(value) == ["<EM4>"]


def test_no_false_positive_on_plain_text():
    assert extract_variables("Просто обычный текст без переменных.") == []
