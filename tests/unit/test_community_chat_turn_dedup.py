from backend.services.ai_chat_service import TurnUpsert, _collapse_duplicate_source_ids


def _turn(source_id: str | None, content: str, sequence: int) -> TurnUpsert:
    return TurnUpsert(
        source_turn_id=source_id,
        role="assistant",
        content=content,
        sequence=sequence,
    )


def test_duplicate_source_ids_collapse_last_write_wins():
    turns = [
        _turn("first", "question", 0),
        _turn("duplicate", "stale", 1),
        _turn("duplicate", "real answer", 2),
    ]

    collapsed = _collapse_duplicate_source_ids(turns)

    assert [(turn.source_turn_id, turn.content) for turn in collapsed] == [
        ("first", "question"),
        ("duplicate", "real answer"),
    ]


def test_idless_turns_are_never_collapsed():
    turns = [_turn(None, "one", 0), _turn(None, "two", 1)]

    assert _collapse_duplicate_source_ids(turns) == turns
