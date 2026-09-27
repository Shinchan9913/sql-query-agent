"""Schema catalog: table, column, foreign-key and index metadata read from the database.

The catalog holds structure only, never row data. It is the single source of
truth for what the agent may reference.
"""

import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    not_null: bool
    primary_key: bool


@dataclass(frozen=True)
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]
    unique: bool


@dataclass
class Table:
    name: str
    columns: list[Column]
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)

    def column(self, name: str) -> Column | None:
        lowered = name.lower()
        return next((c for c in self.columns if c.name.lower() == lowered), None)


class SchemaCatalog:
    """Case-insensitive lookup over the database schema (SQLite identifiers are case-insensitive)."""

    def __init__(self, tables: list[Table]):
        self._tables = {t.name.lower(): t for t in tables}

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "SchemaCatalog":
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return cls([_read_table(conn, name) for name in names])

    @property
    def tables(self) -> list[Table]:
        return list(self._tables.values())

    def table(self, name: str) -> Table | None:
        return self._tables.get(name.lower())

    def relationship_exists(self, table_a: str, column_a: str, table_b: str, column_b: str) -> bool:
        """True if a declared foreign key links the two columns, in either direction."""
        pairs = ((table_a, column_a, table_b, column_b), (table_b, column_b, table_a, column_a))
        for src, src_col, dst, dst_col in pairs:
            table = self.table(src)
            if table and any(
                fk.column.lower() == src_col.lower()
                and fk.ref_table.lower() == dst.lower()
                and fk.ref_column.lower() == dst_col.lower()
                for fk in table.foreign_keys
            ):
                return True
        return False

    def to_sqlglot_schema(self) -> dict[str, dict[str, str]]:
        return {t.name: {c.name: c.type or "TEXT" for c in t.columns} for t in self.tables}

    def to_prompt(self) -> str:
        """Compact DDL-like description of the schema for LLM prompts."""
        blocks = []
        for t in self.tables:
            lines = []
            for c in t.columns:
                flags = [f for f, on in (("PRIMARY KEY", c.primary_key), ("NOT NULL", c.not_null)) if on]
                fk = next((f for f in t.foreign_keys if f.column == c.name), None)
                if fk:
                    flags.append(f"REFERENCES {fk.ref_table}({fk.ref_column})")
                lines.append(f"  {c.name} {c.type}{(' ' + ' '.join(flags)) if flags else ''}")
            blocks.append(f"TABLE {t.name} (\n" + ",\n".join(lines) + "\n)")
        return "\n\n".join(blocks)


def _read_table(conn: sqlite3.Connection, name: str) -> Table:
    quoted = '"' + name.replace('"', '""') + '"'
    columns = [
        Column(name=row[1], type=row[2], not_null=bool(row[3]), primary_key=bool(row[5]))
        for row in conn.execute(f"PRAGMA table_info({quoted})")
    ]
    foreign_keys = [
        ForeignKey(column=row[3], ref_table=row[2], ref_column=row[4])
        for row in conn.execute(f"PRAGMA foreign_key_list({quoted})")
    ]
    indexes = []
    for row in conn.execute(f"PRAGMA index_list({quoted})"):
        index_name, unique = row[1], bool(row[2])
        cols = tuple(r[2] for r in conn.execute(f"PRAGMA index_info(\"{index_name}\")"))
        indexes.append(Index(name=index_name, columns=cols, unique=unique))
    return Table(name=name, columns=columns, foreign_keys=foreign_keys, indexes=indexes)
