from backend.services.artifact_service import _inline_text


def test_text_uploads_are_kept_inline_for_local_search():
    assert _inline_text(b"community local artifact", "text/plain", "code") == ("community local artifact")
    assert _inline_text(b'{"decision":"pgvector"}', "application/json", "file") == ('{"decision":"pgvector"}')


def test_binary_and_large_uploads_are_not_inlined():
    assert _inline_text(b"\x89PNG\x00", "image/png", "image") is None
    assert _inline_text(b"x" * 1_048_577, "text/plain", "code") is None
    assert _inline_text(b"\xff", "text/plain", "code") is None
