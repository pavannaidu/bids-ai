from __future__ import annotations

from server import lakebase


class _RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, statement: str, _params=None) -> None:
        self.statements.append(statement)

    def fetchone(self):
        return None


class _RecordingConnection:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self) -> _RecordingCursor:
        return self._cursor


def test_init_schema_adds_legacy_line_review_columns(monkeypatch):
    cursor = _RecordingCursor()
    monkeypatch.setattr(lakebase, "_connect", lambda: _RecordingConnection(cursor))

    lakebase.init_schema()

    statements = "\n".join(cursor.statements)
    for column_definition in (
        "candidates JSONB NOT NULL DEFAULT '[]'",
        "selected_item_code TEXT",
        "proposed_price NUMERIC",
        "pricing_basis TEXT DEFAULT ''",
        "review_action TEXT NOT NULL DEFAULT 'pending'",
        "reviewer_email TEXT",
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    ):
        assert f"ALTER TABLE bid_line_items ADD COLUMN IF NOT EXISTS {column_definition}" in statements
