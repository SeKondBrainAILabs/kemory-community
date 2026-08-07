from kemory.context.vault_context import _format_section


def test_format_section_omits_an_entry_that_would_be_truncated() -> None:
    content = "AAAK: action, architecture, achievement, and knowledge remain intact"

    rendered = _format_section(
        "Recent Context",
        [{"content": content}],
        max_chars=20,
    )

    assert content not in rendered
    assert content[:10] not in rendered


def test_format_section_keeps_an_entry_whole_when_it_fits() -> None:
    content = "Complete context entry"

    rendered = _format_section(
        "Recent Context",
        [{"content": content}],
        max_chars=100,
    )

    assert f"- {content}" in rendered
