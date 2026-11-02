"""Spike : verifie le pilotage de Claude Code avec la connexion Pro, sans cle API.

Lance dans un dossier temporaire vide, avec un prompt minimal. Prouve que :
- l'authentification passe par l'abonnement (aucune cle dans l'environnement) ;
- le hook PreToolUse se declenche pour chaque outil ;
- une question (AskUserQuestion) remonte jusqu'au callback can_use_tool.
Usage : uv run python tools/spike_claude.py
"""
import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

PROMPT = (
    "Utilise l'outil AskUserQuestion pour me demander quel nom donner au fichier "
    "(options: hello, bye). Puis cree <nom>.txt contenant ok, puis lance `echo ok`. "
    "Sois minimal."
)


async def main() -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    print("cle API dans l'env du processus parent :", "ANTHROPIC_API_KEY" in os.environ)
    tmp = Path(tempfile.mkdtemp(prefix="drvocal_spike_"))
    hook_calls: list[tuple[str, str | None]] = []
    questions: list[dict] = []

    def allowed(name: str, tool_input: dict) -> bool:
        """Liste blanche stricte : tout le reste est refuse."""
        if name == "Write":
            target = Path(tool_input.get("file_path", ""))
            target = target if target.is_absolute() else tmp / target
            return target.resolve().is_relative_to(tmp.resolve())
        if name == "Bash":
            return tool_input.get("command") == "echo ok"
        return name == "AskUserQuestion"

    async def pre_tool(input_data, tool_use_id, context):
        name = input_data["tool_name"]
        hook_calls.append((name, input_data.get("agent_id")))
        print("HOOK", name, input_data["tool_input"])
        if not allowed(name, input_data["tool_input"]):
            decision = "deny"
        else:
            decision = "ask" if name == "AskUserQuestion" else "allow"
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                       "permissionDecisionReason": "spike: liste blanche"}}

    async def can_use_tool(name, tool_input, context):
        print("CAN_USE_TOOL", name, tool_input)
        if not allowed(name, tool_input):
            return PermissionResultDeny(message="spike: refuse")
        if name == "AskUserQuestion":
            questions.append(tool_input)
            answers = {q["question"]: "hello" for q in tool_input.get("questions", [])}
            return PermissionResultAllow(updated_input={**tool_input, "answers": answers})
        return PermissionResultAllow()

    options = ClaudeAgentOptions(
        cwd=tmp, env=env, can_use_tool=can_use_tool,
        hooks={"PreToolUse": [HookMatcher(hooks=[pre_tool])]},
        permission_mode="default", max_turns=8,
    )
    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(PROMPT)
            async for msg in client.receive_response():
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    print("INIT apiKeySource =", msg.data.get("apiKeySource"))
                elif isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, TextBlock):
                            print("TEXT", b.text)
                        elif isinstance(b, ToolUseBlock):
                            print("TOOL_USE", b.name)
                elif isinstance(msg, ResultMessage):
                    print("RESULT", msg.subtype, "error" if msg.is_error else "ok", msg.total_cost_usd)
        print("hooks:", hook_calls)
        print("questions recues:", len(questions))
        print("fichiers:", [p.name for p in tmp.iterdir()])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
