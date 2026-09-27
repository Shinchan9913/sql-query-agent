"""Chat with the agent in the terminal: `python -m app.cli`."""

import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import create_agent


def main() -> None:
    agent = create_agent(InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print("SQL Query Agent. Ask about the database; Ctrl-D to quit.\n")

    while True:
        try:
            message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not message:
            continue

        for update in agent.stream({"messages": [HumanMessage(message)]}, config, stream_mode="updates"):
            for node, values in update.items():
                detail = ""
                if node == "classify_intent":
                    detail = f" -> {values['intent']}"
                elif node == "run_data_tools":
                    entry = values["tool_log"][-1]
                    detail = f" -> {entry['tool']}({entry['args']}) {entry.get('summary') or entry.get('error')}"
                elif node == "validate_sql" and values["validation_errors"]:
                    detail = f" -> rejected: {values['validation_errors']}"
                print(f"  · {node}{detail}")

        response = agent.get_state(config).values["response"]
        print(f"\n[{response['type']}] {response['message']}")
        if response.get("sql"):
            print(f"\n{response['sql']}")
        optimization = response.get("optimization") or {}
        for item in optimization.get("suggestions", []) + optimization.get("index_recommendations", []):
            print(f"  tip: {item}")
        print()


if __name__ == "__main__":
    main()
