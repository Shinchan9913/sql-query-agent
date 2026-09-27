"""Deterministic SQL validation.

Every SQL string the agent returns, every probe query it runs, and every query a
user executes passes through `validate_sql`. The checks, in order:

1. Syntax: parses as SQLite, exactly one statement.
2. Read-only: the statement is a query and contains no write/DDL/admin node
   anywhere in its tree (including CTEs and subqueries).
3. Tables: every referenced table exists in the schema catalog.
4. Columns: every column reference resolves against those tables.
5. Relationships: joins follow declared foreign keys (warning only).
6. Engine: SQLite fully compiles the statement in a zero-row dry run (when a
   connection is given). This catches what the parser accepts but SQLite
   doesn't, e.g. unknown functions.
"""

import difflib
import logging
import re
import sqlite3
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from app.db.catalog import SchemaCatalog

# sqlglot logs a warning for every statement it can't fully parse (e.g. EXPLAIN,
# REPLACE INTO). We reject those statements ourselves, so the noise isn't useful.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECT = "sqlite"

# Node types that must never appear anywhere in a validated statement.
# `Command` is sqlglot's fallback for statements it doesn't model (VACUUM, REPLACE INTO, ...).
_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "TruncateTable",
    "Pragma", "Attach", "Detach", "Transaction", "Commit", "Rollback",
    "Set", "Use", "Copy", "Grant", "Analyze", "Command",
)
_FORBIDDEN_NODES = tuple(getattr(exp, n) for n in _FORBIDDEN_NODE_NAMES if hasattr(exp, n))

_WRITE_KEYWORDS = {
    exp.Insert: "INSERT", exp.Update: "UPDATE", exp.Delete: "DELETE", exp.Drop: "DROP",
    exp.Alter: "ALTER", exp.TruncateTable: "TRUNCATE", exp.Create: "CREATE", exp.Merge: "MERGE",
}

_UNKNOWN_COLUMN_PATTERNS = (
    re.compile(r"Column '([^']+)' could not be resolved"),
    re.compile(r"Unknown column: (\S+)"),
)


@dataclass
class ValidationResult:
    sql: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_sql(
    sql: str, catalog: SchemaCatalog, conn: sqlite3.Connection | None = None
) -> ValidationResult:
    sql = sql.strip().rstrip(";").strip()
    result = ValidationResult(sql=sql)

    if not sql:
        result.errors.append("The SQL query is empty.")
        return result

    statement = _parse_single_statement(sql, result)
    if statement is None:
        return result

    if not _check_read_only(statement, result):
        return result

    if not _check_tables(statement, catalog, result):
        return result

    qualified = _check_columns(statement, catalog, result)
    if qualified is None:
        return result

    _check_joins(qualified, catalog, result)

    if conn is not None:
        _check_with_engine(sql, conn, result)

    return result


def _parse_single_statement(sql: str, result: ValidationResult) -> exp.Expression | None:
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except ParseError as e:
        detail = e.errors[0] if e.errors else {}
        where = f" near line {detail['line']}, column {detail['col']}" if detail.get("line") else ""
        result.errors.append(f"Syntax error{where}: {detail.get('description') or e}")
        return None

    if len(statements) != 1:
        result.errors.append(
            f"Exactly one SQL statement is allowed, but {len(statements)} were found."
        )
        return None
    return statements[0]


def _check_read_only(statement: exp.Expression, result: ValidationResult) -> bool:
    forbidden = next(statement.find_all(*_FORBIDDEN_NODES), None)
    if forbidden is not None:
        keyword = next(
            (kw for cls, kw in _WRITE_KEYWORDS.items() if isinstance(forbidden, cls)),
            forbidden.key.upper(),
        )
        result.errors.append(
            f"Only read-only SELECT queries are allowed; {keyword} statements are not permitted."
        )
        return False

    if not isinstance(statement, exp.Query):
        result.errors.append("Only read-only SELECT queries are allowed.")
        return False
    return True


def _check_tables(statement: exp.Expression, catalog: SchemaCatalog, result: ValidationResult) -> bool:
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    known = [t.name for t in catalog.tables]
    used: list[str] = []

    for table in statement.find_all(exp.Table):
        name = table.name
        if not name:
            continue  # table-valued function or similar; column checks still apply
        if table.catalog or (table.db and table.db.lower() != "main"):
            result.errors.append(f"Table '{table.sql(DIALECT)}' is outside the provided schema.")
            continue
        if name.lower() in cte_names:
            continue
        schema_table = catalog.table(name)
        if schema_table is None:
            result.errors.append(f"Unknown table '{name}'.{_suggest(name, known)}")
        elif schema_table.name not in used:
            used.append(schema_table.name)

    if not result.errors and not used:
        result.errors.append("The query does not reference any table in the provided schema.")

    result.tables = used
    return not result.errors


def _check_columns(
    statement: exp.Expression, catalog: SchemaCatalog, result: ValidationResult
) -> exp.Expression | None:
    """Resolve every column against the schema. Returns the fully qualified tree on success."""
    try:
        return qualify(
            statement.copy(),
            schema=catalog.to_sqlglot_schema(),
            dialect=DIALECT,
            validate_qualify_columns=True,
            identify=False,
        )
    except OptimizeError as e:
        message = str(e)
        for pattern in _UNKNOWN_COLUMN_PATTERNS:
            match = pattern.search(message)
            if match:
                column = match.group(1)
                owners = [t for t in result.tables if catalog.table(t).column(column)]
                if len(owners) > 1:
                    result.errors.append(
                        f"Ambiguous column '{column}': it exists in {', '.join(owners)}. "
                        "Qualify it with a table name or alias."
                    )
                    return None
                candidates = [
                    f"{t}.{c.name}"
                    for t in result.tables
                    for c in catalog.table(t).columns
                ]
                where = f" in table(s) {', '.join(result.tables)}" if result.tables else ""
                result.errors.append(
                    f"Unknown column '{column}'{where}."
                    f"{_suggest(column, candidates, key=lambda c: c.split('.')[1])}"
                )
                return None
        result.errors.append(f"Column reference error: {message.split('. Line:')[0]}")
        return None


def _check_joins(qualified: exp.Expression, catalog: SchemaCatalog, result: ValidationResult) -> None:
    for select in qualified.find_all(exp.Select):
        aliases = {
            t.alias_or_name.lower(): catalog.table(t.name).name
            for t in select.find_all(exp.Table)
            if t.name and catalog.table(t.name)
        }
        for join in select.args.get("joins") or []:
            on = join.args.get("on")
            if on is None or on == exp.true():  # `JOIN t` with no ON parses as `ON TRUE`
                if not join.args.get("using") and join.kind.upper() != "CROSS":
                    result.warnings.append(
                        f"Join with {join.this.sql(DIALECT)} has no condition and produces a cross product."
                    )
                continue
            for eq in on.find_all(exp.EQ):
                left, right = eq.left, eq.right
                if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                    continue
                left_table = aliases.get(left.table.lower())
                right_table = aliases.get(right.table.lower())
                if not left_table or not right_table or left_table == right_table:
                    continue
                if not catalog.relationship_exists(left_table, left.name, right_table, right.name):
                    left_col = catalog.table(left_table).column(left.name)
                    right_col = catalog.table(right_table).column(right.name)
                    result.warnings.append(
                        f"Join condition {left_table}.{left_col.name} = {right_table}.{right_col.name} "
                        "does not follow a declared foreign key; check that it is intended."
                    )


def _check_with_engine(sql: str, conn: sqlite3.Connection, result: ValidationResult) -> None:
    """Compile the statement in SQLite without reading any rows.

    Plain EXPLAIN is not enough: SQLite resolves function names only when a
    statement is prepared for execution. Wrapping in `LIMIT 0` prepares it fully
    and returns immediately. Safe because the statement has already been
    verified as a single read-only query.
    """
    try:
        conn.execute(f"SELECT * FROM ({sql}) LIMIT 0").fetchall()
    except sqlite3.Error as e:
        result.errors.append(f"The database rejected the query: {e}")


def _suggest(name: str, candidates: list[str], key=lambda c: c) -> str:
    by_key = {key(c).lower(): c for c in candidates}
    matches = difflib.get_close_matches(name.lower(), list(by_key), n=3, cutoff=0.6)
    if not matches:
        return ""
    return " Did you mean: " + ", ".join(by_key[m] for m in matches) + "?"
