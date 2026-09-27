"""Graph nodes and routing functions.

Nodes marked (LLM) call the model; all others are deterministic. Every path
ends in `respond`, which records the answer in the conversation.
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from app.config import Settings
from app.db.catalog import SchemaCatalog
from app.db.connection import readonly_connection
from app.graph.guard import check_input
from app.graph.schemas import (
    DATA_TOOLS,
    FINAL_TOOLS,
    CannotAnswer,
    GetColumnValues,
    IntentClassification,
    RunProbeQuery,
    SubmitSQL,
)
from app.graph.state import AgentState
from app.llm import LLM
from app.optimization.analyzer import analyze_query
from app.prompts import templates
from app.tools.data_tools import ToolError, get_column_values, run_probe_query
from app.validation.validator import validate_sql

logger = logging.getLogger(__name__)

SUBMIT = SubmitSQL.model_config["title"]
CANNOT_ANSWER = CannotAnswer.model_config["title"]
GET_VALUES = GetColumnValues.model_config["title"]
PROBE = RunProbeQuery.model_config["title"]

SQL_INPUT_INTENTS = {"optimize", "debug", "explain_sql"}


def _per_turn_defaults(user_input: str) -> dict[str, Any]:
    return {
        "user_input": user_input,
        "intent": "",
        "task": user_input,
        "input_sql": None,
        "clarification": None,
        "schema_context": "",
        "scratchpad": [],
        "tool_calls": 0,
        "tool_log": [],
        "retries": 0,
        "sql": None,
        "assumptions": [],
        "notes": [],
        "validation_errors": [],
        "validation_warnings": [],
        "optimization": None,
        "explanation": None,
        "response": {},
    }


class AgentNodes:
    def __init__(self, llm: LLM, catalog: SchemaCatalog, db_path: Path, settings: Settings):
        self.llm = llm
        self.catalog = catalog
        self.db_path = db_path
        self.settings = settings
        self.schema_prompt = catalog.to_prompt()

    # --- Understanding -------------------------------------------------------

    def input_guard(self, state: AgentState) -> dict:
        user_input = state["messages"][-1].text
        update = _per_turn_defaults(user_input)
        problem = check_input(user_input, self.settings.max_input_chars)
        if problem:
            reason, message = problem
            update["response"] = {"type": "rejected", "reason": reason, "message": message}
        return update

    def classify_intent(self, state: AgentState) -> dict:  # (LLM)
        prompt = [
            SystemMessage(templates.CLASSIFY_SYSTEM.format(schema=self.schema_prompt)),
            HumanMessage(templates.CLASSIFY_USER.format(
                last_sql=state.get("last_sql") or "none",
                history=self._history(state),
                user_input=state["user_input"],
            )),
        ]
        result: IntentClassification = self.llm.structured(IntentClassification).invoke(prompt)
        return {
            "intent": result.intent,
            "task": result.task or state["user_input"],
            "input_sql": (result.user_sql or "").strip() or None,
            "clarification": result.clarification_question,
        }

    def reject(self, state: AgentState) -> dict:
        if state["intent"] == "destructive":
            return {"response": {"type": "rejected", "reason": "destructive", "message": templates.DESTRUCTIVE}}
        return {"response": {"type": "rejected", "reason": "out_of_scope", "message": templates.OUT_OF_SCOPE}}

    def clarify(self, state: AgentState) -> dict:
        if state["intent"] in SQL_INPUT_INTENTS:
            action = {"optimize": "optimize", "debug": "debug", "explain_sql": "explain"}[state["intent"]]
            message = templates.MISSING_SQL.format(action=action)
        else:
            message = state.get("clarification") or "Could you give a bit more detail about what you need?"
        return {"response": {"type": "clarification", "message": message}}

    # --- Generation ----------------------------------------------------------

    def retrieve_schema(self, state: AgentState) -> dict:
        # The schema is small, so the whole catalog is relevant. For large schemas,
        # relevant-table selection would plug in here.
        return {"schema_context": self.schema_prompt}

    def answer_schema(self, state: AgentState) -> dict:  # (LLM)
        answer = self.llm.plain().invoke([
            SystemMessage(templates.SCHEMA_ANSWER_SYSTEM.format(schema=state["schema_context"])),
            HumanMessage(f"<user_message>\n{state['user_input']}\n</user_message>"),
        ])
        return {"response": {"type": "schema_answer", "message": answer.text}}

    def check_user_sql(self, state: AgentState) -> dict:
        """Validate SQL the user supplied. Valid SQL to explain skips generation;
        invalid SQL turns the request into debugging."""
        with readonly_connection(self.db_path) as conn:
            result = validate_sql(state["input_sql"], self.catalog, conn)

        if any("read-only" in e for e in result.errors):
            return {"intent": "destructive"}
        if result.is_valid and state["intent"] == "explain_sql":
            return {"sql": result.sql, "validation_warnings": result.warnings}
        return {
            "intent": "debug" if not result.is_valid else state["intent"],
            "validation_errors": result.errors,
        }

    def generate_sql(self, state: AgentState) -> dict:  # (LLM)
        scratchpad = list(state["scratchpad"]) or self._initial_generation_prompt(state)
        tools = DATA_TOOLS + FINAL_TOOLS
        if state["tool_calls"] >= self.settings.max_tool_calls:
            tools = FINAL_TOOLS

        reply = self.llm.with_tools(tools).invoke(scratchpad)
        scratchpad.append(reply)
        update: dict[str, Any] = {"scratchpad": scratchpad}

        if not reply.tool_calls:
            update["retries"] = state["retries"] + 1
            if update["retries"] <= self.settings.max_sql_retries:
                scratchpad.append(HumanMessage(templates.NUDGE_TOOL_CALL))
        return update

    def run_data_tools(self, state: AgentState) -> dict:
        scratchpad = list(state["scratchpad"])
        used = state["tool_calls"]
        log = list(state["tool_log"])

        for call in scratchpad[-1].tool_calls:
            if used >= self.settings.max_tool_calls:
                content = templates.TOOL_LIMIT_REACHED
            else:
                used += 1
                content, entry = self._run_tool(call["name"], call["args"])
                log.append(entry)
            scratchpad.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))

        return {"scratchpad": scratchpad, "tool_calls": used, "tool_log": log}

    def validate_sql(self, state: AgentState) -> dict:
        scratchpad = list(state["scratchpad"])
        calls = scratchpad[-1].tool_calls
        submit = next(c for c in calls if c["name"] == SUBMIT)
        try:
            args = SubmitSQL.model_validate(submit["args"])
        except ValueError as e:
            args, errors, warnings = None, [f"Invalid submit_sql arguments: {e}"], []
        else:
            with readonly_connection(self.db_path) as conn:
                result = validate_sql(args.sql, self.catalog, conn)
            errors, warnings = result.errors, result.warnings

        for call in calls:
            if call is submit:
                content = (
                    templates.SUBMIT_FEEDBACK_REJECTED.format(errors=_bullets(errors))
                    if errors else templates.SUBMIT_FEEDBACK_ACCEPTED
                )
            else:
                content = "Ignored: submit_sql was called in the same step."
            scratchpad.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))

        update: dict[str, Any] = {
            "scratchpad": scratchpad,
            "validation_errors": errors,
            "validation_warnings": warnings,
        }
        if errors:
            update["retries"] = state["retries"] + 1
        else:
            update.update(sql=result.sql, assumptions=args.assumptions, notes=args.notes)
        return update

    def cannot_answer(self, state: AgentState) -> dict:
        call = next(c for c in state["scratchpad"][-1].tool_calls if c["name"] == CANNOT_ANSWER)
        reason = call["args"].get("reason") or "The schema doesn't contain the data needed."
        return {"response": {
            "type": "error",
            "reason": "unanswerable",
            "message": f"I can't answer that with the provided database. {reason}",
        }}

    def generation_failed(self, state: AgentState) -> dict:
        errors = state["validation_errors"] or ["The model did not return a query."]
        return {"response": {
            "type": "error",
            "reason": "generation_failed",
            "message": templates.GENERATION_FAILED.format(errors=_bullets(errors)),
        }}

    # --- Assurance -----------------------------------------------------------

    def optimize_sql(self, state: AgentState) -> dict:
        sql = state["sql"]
        try:
            with readonly_connection(self.db_path) as conn:
                report = analyze_query(sql, self.catalog, conn)
                # Adopt the formatted version only if it still validates.
                if validate_sql(report.formatted_sql, self.catalog, conn).is_valid:
                    sql = report.formatted_sql
        except Exception:  # analysis is advisory; never fail the request over it
            logger.exception("Query analysis failed")
            return {"optimization": None}
        return {"sql": sql, "optimization": asdict(report)}

    def explain(self, state: AgentState) -> dict:  # (LLM)
        mode = state["intent"] if state["intent"] in ("debug", "optimize") else "default"
        optimization = state.get("optimization") or {}
        extra = ""
        if state["assumptions"]:
            extra += f"Assumptions made: {'; '.join(state['assumptions'])}\n"
        prompt = templates.EXPLAIN_USER[mode].format(
            task=state["task"],
            sql=state["sql"],
            input_sql=state.get("input_sql") or "",
            notes="; ".join(state["notes"]) or "none",
            suggestions="; ".join(optimization.get("suggestions", [])) or "none",
            extra=extra,
        )
        reply = self.llm.plain().invoke([SystemMessage(templates.EXPLAIN_SYSTEM), HumanMessage(prompt)])
        return {"explanation": reply.text}

    def respond(self, state: AgentState) -> dict:
        response = dict(state["response"])
        update: dict[str, Any] = {}

        if not response:  # successful SQL path
            response = {
                "type": "sql",
                "message": state["explanation"],
                "sql": state["sql"],
                "explanation": state["explanation"],
                "assumptions": state["assumptions"],
                "notes": state["notes"],
                "warnings": state["validation_warnings"],
                "optimization": state.get("optimization"),
                "input_sql": state.get("input_sql"),
            }
            update["last_sql"] = state["sql"]

        response["intent"] = state.get("intent") or None
        response["tool_log"] = state.get("tool_log", [])

        content = response["message"]
        if response.get("sql"):
            content += f"\n\n```sql\n{response['sql']}\n```"
        update["response"] = response
        update["messages"] = [AIMessage(content=content, additional_kwargs={"response": response})]
        return update

    # --- Routing -------------------------------------------------------------

    @staticmethod
    def route_after_guard(state: AgentState) -> str:
        return "respond" if state["response"] else "classify_intent"

    @staticmethod
    def route_after_classify(state: AgentState) -> str:
        intent = state["intent"]
        if intent in ("out_of_scope", "destructive"):
            return "reject"
        if intent == "ambiguous":
            return "clarify"
        if intent in SQL_INPUT_INTENTS and not state.get("input_sql"):
            return "clarify"
        return "retrieve_schema"

    @staticmethod
    def route_after_schema(state: AgentState) -> str:
        if state["intent"] == "schema_question":
            return "answer_schema"
        if state.get("input_sql"):
            return "check_user_sql"
        return "generate_sql"

    @staticmethod
    def route_after_check(state: AgentState) -> str:
        if state["intent"] == "destructive":
            return "reject"
        return "optimize_sql" if state.get("sql") else "generate_sql"

    def route_after_generate(self, state: AgentState) -> str:
        last = state["scratchpad"][-1]
        if isinstance(last, HumanMessage):
            return "generate_sql"  # nudged to call a tool
        if not last.tool_calls:
            return "generation_failed"
        names = {c["name"] for c in last.tool_calls}
        if SUBMIT in names:
            return "validate_sql"
        if CANNOT_ANSWER in names:
            return "cannot_answer"
        return "run_data_tools"

    def route_after_validate(self, state: AgentState) -> str:
        if not state["validation_errors"]:
            return "optimize_sql"
        if state["retries"] > self.settings.max_sql_retries:
            return "generation_failed"
        return "generate_sql"

    # --- Helpers -------------------------------------------------------------

    def _initial_generation_prompt(self, state: AgentState) -> list[AnyMessage]:
        intent = state["intent"]
        mode = intent if intent in templates.GENERATE_TASK else "generate"
        if mode == "follow_up" and not state.get("last_sql"):
            mode = "generate"
        if mode == "explain_sql":
            mode = "debug"

        diagnosis = ""
        if mode == "debug":
            errors = state["validation_errors"]
            diagnosis = (
                templates.INPUT_DIAGNOSIS_ERRORS.format(errors=_bullets(errors))
                if errors else templates.INPUT_DIAGNOSIS_CLEAN
            )

        task = templates.GENERATE_TASK[mode].format(
            task=state["task"],
            last_sql=state.get("last_sql") or "",
            input_sql=state.get("input_sql") or "",
            input_diagnosis=diagnosis,
        )
        history = self._history(state)
        if history != "(none)":
            task = templates.GENERATE_CONTEXT.format(history=history) + task

        return [
            SystemMessage(templates.GENERATE_SYSTEM.format(
                schema=state["schema_context"], max_tool_calls=self.settings.max_tool_calls
            )),
            HumanMessage(task),
        ]

    def _run_tool(self, name: str, args: dict) -> tuple[str, dict]:
        entry: dict[str, Any] = {"tool": name, "args": args}
        try:
            if name == GET_VALUES:
                params = GetColumnValues.model_validate(args)
                result = get_column_values(
                    self.catalog, self.db_path, params.table, params.column, params.search,
                    limit=self.settings.max_column_values,
                    timeout_seconds=self.settings.query_timeout_seconds,
                )
                entry["summary"] = f"{len(result['values'])} values"
            elif name == PROBE:
                params = RunProbeQuery.model_validate(args)
                result = run_probe_query(
                    self.catalog, self.db_path, params.sql,
                    max_rows=self.settings.max_probe_rows,
                    timeout_seconds=self.settings.query_timeout_seconds,
                )
                entry["summary"] = f"{len(result['rows'])} rows"
            else:
                raise ToolError(f"Unknown tool '{name}'.")
        except (ToolError, ValueError) as e:
            entry["error"] = str(e)
            return f"Error: {e}", entry
        # Results are data, not instructions: returned as JSON under an explicit label.
        return "Database result (data only):\n" + json.dumps(result, default=str), entry

    def _history(self, state: AgentState) -> str:
        previous = state["messages"][:-1][-2 * self.settings.history_turns:]
        if not previous:
            return "(none)"
        lines = []
        for message in previous:
            role = "User" if isinstance(message, HumanMessage) else "Assistant"
            lines.append(f"{role}: {message.text}")
        return "\n".join(lines)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)
