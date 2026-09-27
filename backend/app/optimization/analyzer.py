"""Deterministic query analysis: formatting, plan-based index advice, anti-patterns and cost.

Uses `EXPLAIN QUERY PLAN`, which reports how SQLite would run a statement
without running it. Table row counts for the cost estimate are read by
application code, not by the model.
"""

import re
import sqlite3
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify

from app.db.catalog import SchemaCatalog
from app.validation.validator import DIALECT

# "SCAN t", "SCAN t USING INDEX i" and "SCAN t USING COVERING INDEX i" all read every row.
_FULL_SCAN = re.compile(r"^SCAN (\S+)")
_TRANSPILE_DIALECTS = ("postgres", "mysql")


@dataclass
class OptimizationReport:
    formatted_sql: str
    suggestions: list[str] = field(default_factory=list)
    index_recommendations: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    dialects: dict[str, str] = field(default_factory=dict)


def analyze_query(sql: str, catalog: SchemaCatalog, conn: sqlite3.Connection) -> OptimizationReport:
    """Analyze an already-validated read-only query."""
    tree = sqlglot.parse_one(sql, read=DIALECT)
    qualified = qualify(tree.copy(), schema=catalog.to_sqlglot_schema(), dialect=DIALECT, identify=False)
    aliases = _alias_map(qualified, catalog)

    report = OptimizationReport(formatted_sql=format_sql(sql))
    report.plan = [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
    scanned = _full_scans(report.plan, aliases)

    report.index_recommendations = _index_recommendations(qualified, catalog, aliases, scanned)
    report.suggestions = _anti_patterns(tree, qualified, catalog, aliases)
    report.cost = _estimate_cost(conn, scanned, report.plan)
    report.dialects = _transpile(sql)
    return report


def format_sql(sql: str) -> str:
    return sqlglot.transpile(sql, read=DIALECT, write=DIALECT, pretty=True)[0]


def _transpile(sql: str) -> dict[str, str]:
    out = {"sqlite": format_sql(sql)}
    for dialect in _TRANSPILE_DIALECTS:
        try:
            out[dialect] = sqlglot.transpile(sql, read=DIALECT, write=dialect, pretty=True)[0]
        except sqlglot.errors.SqlglotError:
            pass  # not every SQLite construct has an equivalent; skip that dialect
    return out


def _alias_map(qualified: exp.Expression, catalog: SchemaCatalog) -> dict[str, str]:
    """alias (lowercase) -> real table name, for tables in the schema (CTEs excluded)."""
    return {
        t.alias_or_name.lower(): catalog.table(t.name).name
        for t in qualified.find_all(exp.Table)
        if t.name and catalog.table(t.name)
    }


def _full_scans(plan: list[str], aliases: dict[str, str]) -> list[str]:
    """Real tables SQLite reads end to end rather than searching by key."""
    tables = []
    for detail in plan:
        match = _FULL_SCAN.match(detail.strip())
        if match:
            table = aliases.get(match.group(1).lower())
            if table and table not in tables:
                tables.append(table)
    return tables


def _filter_columns(qualified: exp.Expression, aliases: dict[str, str]) -> list[tuple[str, str]]:
    """(table, column) pairs used in WHERE and JOIN conditions."""
    pairs: list[tuple[str, str]] = []
    conditions = [w.this for w in qualified.find_all(exp.Where)]
    conditions += [j.args["on"] for j in qualified.find_all(exp.Join) if j.args.get("on")]
    for condition in conditions:
        for column in condition.find_all(exp.Column):
            table = aliases.get(column.table.lower())
            if table and (table, column.name.lower()) not in pairs:
                pairs.append((table, column.name.lower()))
    return pairs


def _index_recommendations(
    qualified: exp.Expression, catalog: SchemaCatalog, aliases: dict[str, str], scanned: list[str]
) -> list[str]:
    recommendations = []
    for table_name, column_name in _filter_columns(qualified, aliases):
        if table_name not in scanned:
            continue
        table = catalog.table(table_name)
        column = table.column(column_name)
        already_leading = any(i.columns and i.columns[0].lower() == column_name for i in table.indexes)
        if column is None or column.primary_key or already_leading:
            continue
        recommendations.append(
            f"CREATE INDEX idx_{table.name.lower()}_{column.name.lower()} ON {table.name}({column.name});"
        )
    return recommendations


def _anti_patterns(
    tree: exp.Expression, qualified: exp.Expression, catalog: SchemaCatalog, aliases: dict[str, str]
) -> list[str]:
    suggestions = []

    if any(isinstance(e, exp.Star) for s in tree.find_all(exp.Select) for e in s.expressions):
        suggestions.append(
            "Select only the columns you need instead of SELECT *; it reads less data and "
            "keeps results stable if the table changes."
        )

    for where in tree.find_all(exp.Where):
        for func in where.find_all(exp.Func):
            if isinstance(func, (exp.And, exp.Or, exp.Not)) or func.find_ancestor(exp.Subquery):
                continue
            wrapped = func.find(exp.Column)
            if wrapped is not None and not isinstance(func, exp.Predicate) and func is not wrapped:
                suggestions.append(
                    f"The filter wraps a column in {func.sql(DIALECT)}, which stops SQLite from using an "
                    "index on it; compare the raw column instead (e.g. a date range rather than strftime)."
                )
                break

        for like in where.find_all(exp.Like):
            pattern = like.expression
            if isinstance(pattern, exp.Literal) and pattern.this.startswith("%"):
                suggestions.append(
                    f"LIKE '{pattern.this}' starts with a wildcard, so it cannot use an index."
                )

    suggestions.extend(_unused_joins(qualified, catalog, aliases))
    return suggestions


def _unused_joins(qualified: exp.Expression, catalog: SchemaCatalog, aliases: dict[str, str]) -> list[str]:
    """Joined tables whose columns appear only in their own join condition.

    Such a LEFT JOIN is removable only if it matches at most one row, i.e. the
    joined table is matched on its primary key; otherwise it can duplicate rows.
    """
    notes = []
    for select in qualified.find_all(exp.Select):
        for join in select.args.get("joins") or []:
            alias = join.this.alias_or_name.lower()
            if alias not in aliases or not join.args.get("on"):
                continue
            on_columns = set(map(id, join.args["on"].find_all(exp.Column)))
            used_elsewhere = any(
                c.table.lower() == alias and id(c) not in on_columns
                for c in select.find_all(exp.Column)
            )
            if used_elsewhere:
                continue
            table = aliases[alias]
            if join.side.upper() != "LEFT":
                effect = "it only filters rows to those with a match; remove it if that isn't intended"
            elif _matches_on_primary_key(join.args["on"], alias, catalog.table(table)):
                effect = "it cannot change the result and can be removed"
            else:
                effect = "it may duplicate rows; remove it unless that is intended"
            notes.append(f"The join to {table} contributes no columns; {effect}.")
    return notes


def _matches_on_primary_key(on: exp.Expression, alias: str, table) -> bool:
    joined = {c.name.lower() for c in on.find_all(exp.Column) if c.table.lower() == alias}
    primary_key = {c.name.lower() for c in table.columns if c.primary_key}
    return bool(primary_key) and primary_key <= joined


def _estimate_cost(conn: sqlite3.Connection, scanned: list[str], plan: list[str]) -> dict:
    rows_scanned = 0
    for table in scanned:
        quoted = '"' + table.replace('"', '""') + '"'
        rows_scanned += conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]

    temp_structures = sum("TEMP B-TREE" in d for d in plan)
    if rows_scanned > 100_000 or (rows_scanned > 10_000 and temp_structures):
        level = "high"
    elif rows_scanned > 1_000 or temp_structures > 1:
        level = "medium"
    else:
        level = "low"

    return {
        "level": level,
        "full_scans": scanned,
        "rows_scanned_estimate": rows_scanned,
        "uses_temp_sort": temp_structures > 0,
    }
