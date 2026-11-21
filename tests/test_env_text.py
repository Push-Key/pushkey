"""Pure text helpers for the variables a key is connected to in an env file."""
from __future__ import annotations

import pushkey_env
from pushkey_env import (
    EnvLine,
    apply_env_assignments,
    decode_env_value,
    format_env_value,
    parse_env_lines,
    render_connected_value,
    sanitize_env_value,
)

HEADER = "# Managed by Pushkey"


def _error_of(call):
    """The ValueError `call` raises, or None (keeps a missing raise an assertion, not a pytest Failed)."""
    try:
        call()
    except ValueError as exc:
        return exc
    return None


# --- parse_env_lines -------------------------------------------------------


def test_parse_keeps_case_and_export():
    lines = parse_env_lines("export NEXT_PUBLIC_X=1\n  B = 2\n# c\n")
    assert [line.name for line in lines] == ["NEXT_PUBLIC_X", "B"]
    assert lines[0].export is True
    assert lines[1].export is False


def test_parse_reports_index_value_text_and_export():
    text = '# note\n\nexport A = 1  \n\tb="x y"\r\nA=2\nlast=z'
    assert parse_env_lines(text) == [
        EnvLine(index=2, name="A", value_text="1", export=True),
        EnvLine(index=3, name="b", value_text='"x y"', export=False),
        EnvLine(index=4, name="A", value_text="2", export=False),
        EnvLine(index=5, name="last", value_text="z", export=False),
    ]


def test_parse_ignores_a_leading_bom_and_non_assignments():
    text = "﻿A=1\n# B=2\nC D=3\n1E=4\nexport F\nexport=5\nexportG=6\n"
    lines = parse_env_lines(text)
    assert [(line.index, line.name, line.export) for line in lines] == [
        (0, "A", False),
        (5, "export", False),
        (6, "exportG", False),
    ]
    assert [line.value_text for line in lines] == ["1", "5", "6"]


def test_parse_splits_on_newline_only():
    # \x0c, \x85 and   are line breaks for str.splitlines but not for env files.
    text = "A=a\x0cb\nB=c d\nC=e\x85f\n"
    lines = parse_env_lines(text)
    assert [(line.index, line.name, line.value_text) for line in lines] == [
        (0, "A", "a\x0cb"),
        (1, "B", "c d"),
        (2, "C", "e\x85f"),
    ]


# --- decode_env_value ------------------------------------------------------


def test_decode_round_trips_format():
    for v in ["plain", "with space", 'q"uote', "a#b", ""]:
        assert decode_env_value(format_env_value(v)) == v, v
    assert decode_env_value("'lit $x'") == "lit $x"


def test_decode_round_trips_format_for_awkward_values():
    values = [
        "a \\n b",  # a space, a backslash and an n: not a newline
        "x y\\",  # ends with a backslash
        "tab\there",
        "l1\nl2",
        "cr\rlf",
        'say "hi" \\" now',
        " lead",
        "trail ",
        "a=b",
        "$HOME `x`",
        "back\\slash",
        "\\\\",
    ]
    for v in values:
        assert decode_env_value(format_env_value(v)) == v, v


def test_decode_text_that_is_not_quoted_is_returned_as_is():
    assert decode_env_value("abc") == "abc"
    assert decode_env_value("a b") == "a b"
    assert decode_env_value('"') == '"'
    assert decode_env_value("'") == "'"
    assert decode_env_value("'abc") == "'abc"
    assert decode_env_value("abc\"") == "abc\""
    assert decode_env_value("a\\nb") == "a\\nb"


def test_decode_double_quoted_decodes_left_to_right_and_leaves_other_escapes():
    assert decode_env_value(r'"a\nb\\nc"') == "a\nb\\nc"
    assert decode_env_value(r'"a\qb"') == "a\\qb"
    assert decode_env_value(r'"say \"hi\""') == 'say "hi"'
    assert decode_env_value("'a\\nb'") == "a\\nb"  # single quotes are literal
    assert decode_env_value('"a\rb"') == "a\rb"  # a raw carriage return is content


# --- render_connected_value ------------------------------------------------


def test_render_strips_line_breaks_then_formats():
    assert render_connected_value("plain") == "plain"
    assert render_connected_value("a\nb c") == '"ab c"'
    assert render_connected_value("a\r\nb") == "ab"
    assert render_connected_value('q"uote') == '"q\\"uote"'
    assert render_connected_value("") == '""'
    assert render_connected_value(123) == "123"


def test_render_is_the_one_transform_for_writing_and_comparing():
    for v in ["plain", "with space", 'q"uote', "a#b", "", "l1\nl2 x", "back\\slash", " pad "]:
        assert render_connected_value(v) == format_env_value(sanitize_env_value(v)), v
        assert decode_env_value(render_connected_value(v)) == sanitize_env_value(v), v


def test_render_then_parse_survives_unusual_line_separators():
    for v in ["a\x0cb", "a b", "a\x85b", "tab\there", "x\x0b"]:
        rendered = render_connected_value(v)
        lines = parse_env_lines("K=" + rendered + "\n")
        assert [line.value_text for line in lines] == [rendered], repr(v)
        assert decode_env_value(lines[0].value_text) == v, repr(v)


# --- apply_env_assignments -------------------------------------------------


def test_apply_assignments_keeps_crlf_bom_export_and_dupes():
    text = "﻿export A=1\r\nB=2\r\nA=old\r\n"
    new_text, added, updated = apply_env_assignments(text, {"A": "9", "C": "3"})
    assert new_text == "﻿export A=9\r\nB=2\r\nA=9\r\n\r\n# Managed by Pushkey\r\nC=3\r\n"
    assert added == ["C"]
    assert updated == ["A"]


def test_apply_assignments_header_once():
    text = "# Managed by Pushkey\nC=3\n"
    new_text, added, updated = apply_env_assignments(text, {"D": "4"})
    assert new_text == "# Managed by Pushkey\nC=3\nD=4\n"
    assert added == ["D"]
    assert updated == []
    assert new_text.count(HEADER) == 1


def test_apply_assignments_second_run_adds_nothing_and_changes_nothing():
    first, added, _ = apply_env_assignments("X=1\n", {"A": "1", "B": '"b c"'})
    assert added == ["A", "B"]
    second, added2, updated2 = apply_env_assignments(first, {"A": "1", "B": '"b c"'})
    assert second == first
    assert added2 == []
    assert updated2 == ["A", "B"]
    assert second.count(HEADER) == 1


def test_apply_adds_the_header_after_a_blank_line_unless_one_is_there():
    text, added, _ = apply_env_assignments("X=1\n", {"A": "1"})
    assert text == "X=1\n\n# Managed by Pushkey\nA=1\n"
    assert added == ["A"]
    text, _, _ = apply_env_assignments("X=1\n\n", {"A": "1"})
    assert text == "X=1\n\n# Managed by Pushkey\nA=1\n"


def test_apply_to_empty_text_starts_with_the_header():
    text, added, updated = apply_env_assignments("", {"A": "1", "B": "2"})
    assert text == "# Managed by Pushkey\nA=1\nB=2\n"
    assert (added, updated) == (["A", "B"], [])


def test_apply_to_a_bom_only_file_keeps_the_bom():
    text, added, _ = apply_env_assignments("﻿", {"A": "1"})
    assert text == "﻿# Managed by Pushkey\nA=1\n"
    assert added == ["A"]


def test_apply_lf_text_without_final_newline_gets_one_and_stays_lf():
    text, added, updated = apply_env_assignments("A=1\nB=2", {"A": "9"})
    assert text == "A=9\nB=2\n"
    assert (added, updated) == ([], ["A"])
    text, _, _ = apply_env_assignments("A=1\nB=2", {"C": "3"})
    assert text == "A=1\nB=2\n\n# Managed by Pushkey\nC=3\n"


def test_apply_crlf_text_without_final_newline_ends_with_crlf():
    text, _, _ = apply_env_assignments("A=1\r\nB=2", {"B": "9"})
    assert text == "A=1\r\nB=9\r\n"
    text, _, _ = apply_env_assignments("A=1\r\nB=2", {"C": "3"})
    assert text == "A=1\r\nB=2\r\n\r\n# Managed by Pushkey\r\nC=3\r\n"


def test_apply_keeps_every_other_line_exactly():
    text = "# note\r\nX = 'a b'  \n\n  # indented comment\nA=1\r\n#A=3\nY=\"q\" # c\n"
    new_text, added, updated = apply_env_assignments(text, {"A": "2"})
    assert new_text == "# note\r\nX = 'a b'  \n\n  # indented comment\nA=2\r\n#A=3\nY=\"q\" # c\n"
    assert (added, updated) == ([], ["A"])


def test_apply_keeps_indentation_and_export_spacing_and_normalises_the_equals():
    text = "  A = 1\n\texport B=2\nexport   C = 3\n"
    new_text, _, updated = apply_env_assignments(text, {"A": "x", "B": "y", "C": "z"})
    assert new_text == "  A=x\n\texport B=y\nexport   C=z\n"
    assert updated == ["A", "B", "C"]


def test_apply_replaces_every_duplicate_and_counts_it_once():
    text = "A=1\nB=2\nA=3\nexport A=4\n"
    new_text, added, updated = apply_env_assignments(text, {"A": "9"})
    assert new_text == "A=9\nB=2\nA=9\nexport A=9\n"
    assert (added, updated) == ([], ["A"])


def test_apply_lists_names_in_assignment_order():
    text = "B=1\nA=1\n"
    new_text, added, updated = apply_env_assignments(text, {"Z": "1", "A": "2", "Y": "3", "B": "4"})
    assert new_text == "B=4\nA=2\n\n# Managed by Pushkey\nZ=1\nY=3\n"
    assert added == ["Z", "Y"]
    assert updated == ["A", "B"]


def test_apply_variable_names_are_case_sensitive_and_comments_are_not_assignments():
    new_text, added, updated = apply_env_assignments("a=1\n# A=2\n", {"A": "9"})
    assert new_text == "a=1\n# A=2\n\n# Managed by Pushkey\nA=9\n"
    assert (added, updated) == (["A"], [])


def test_apply_inserts_values_as_given_because_they_are_already_rendered():
    rendered = render_connected_value("with space")
    new_text, _, _ = apply_env_assignments("A=1\n", {"A": rendered, "B": "x\\ny"})
    assert new_text == 'A="with space"\n\n# Managed by Pushkey\nB=x\\ny\n'


def test_apply_mixed_line_endings_keep_their_own_ending_and_new_lines_use_crlf():
    text = "A=1\nB=2\r\nC=3\n"
    new_text, added, updated = apply_env_assignments(text, {"A": "9", "D": "4"})
    assert new_text == "A=9\nB=2\r\nC=3\n\r\n# Managed by Pushkey\r\nD=4\r\n"
    assert (added, updated) == (["D"], ["A"])


def test_apply_leaves_a_lone_carriage_return_inside_the_line():
    new_text, _, updated = apply_env_assignments("A=1\rB=2\n", {"B": "9"})
    assert new_text == "A=1\rB=2\n\n# Managed by Pushkey\nB=9\n"
    assert updated == []


def test_apply_with_no_assignments_only_ends_the_text_with_a_newline():
    assert apply_env_assignments("A=1", {}) == ("A=1\n", [], [])
    assert apply_env_assignments("﻿A=1\r\n", {}) == ("﻿A=1\r\n", [], [])
    assert apply_env_assignments("A=1\n", {})[0] == "A=1\n"


def test_apply_rejects_names_and_values_that_would_break_the_file():
    err = _error_of(lambda: apply_env_assignments("A=1\n", {"A B": "1"}))
    assert err is not None
    assert "A B" in str(err)
    assert _error_of(lambda: apply_env_assignments("A=1\n", {"1A": "1"})) is not None
    assert _error_of(lambda: apply_env_assignments("A=1\n", {"A\nB": "1"})) is not None
    err = _error_of(lambda: apply_env_assignments("A=1\n", {"A": "s3cret\nEVIL=1"}))
    assert err is not None
    assert "s3cret" not in str(err)  # a value never goes into a message
    assert _error_of(lambda: apply_env_assignments("A=1\n", {"A": "x\ry"})) is not None


def test_apply_then_parse_and_decode_gives_back_the_values():
    values = {
        "PLAIN": "plain",
        "SPACED": "with space",
        "QUOTED": 'q"uote',
        "HASH": "a#b",
        "EMPTY": "",
        "SLASH": "back\\slash",
        "BREAK": "l1\nl2",
    }
    assignments = {name: render_connected_value(v) for name, v in values.items()}
    text, added, _ = apply_env_assignments("﻿X=1\r\n", assignments)
    assert added == list(values)
    parsed = {line.name: decode_env_value(line.value_text) for line in parse_env_lines(text)}
    assert parsed == {"X": "1", **{n: sanitize_env_value(v) for n, v in values.items()}}


def test_the_existing_env_line_pattern_is_left_alone():
    assert pushkey_env._ENV_LINE.match("export A=1") is None
    assert pushkey_env._ENV_LINE.match("A=1").group(2) == "1"
