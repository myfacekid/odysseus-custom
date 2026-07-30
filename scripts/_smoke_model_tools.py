"""Ephemeral smoke test: dispatch every model-facing command through the real
agent tool dispatcher with benign / read-only args and classify the outcome.

Not a pytest — run directly:  venv/bin/python scripts/_smoke_model_tools.py
Categories:
  PASS   exit_code == 0 (executed successfully)
  WIRED  clean {"error":...,"exit_code":1} (handler reached, graceful guard:
         needs config/model/active-doc/project/running-server/valid-id)
  FAIL   raised exception, "Unknown tool type", or timeout
"""
import asyncio
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OWNER = "kincaidr"
PER_TOOL_TIMEOUT = 25.0

from src.agent_tools import TOOL_TAGS
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, function_call_to_tool_block
from src.agent_tools import ToolBlock
from src.tool_execution import execute_tool_block

# name -> benign JSON args (read-only / list / validation-only wherever possible)
BENIGN = {
    "bash": {"command": "echo smoketest_ok"},
    "python": {"code": "print('smoketest_ok')"},
    "web_search": {"query": "wikipedia"},
    "search_zotero": {"action": "list_collections"},
    "search_knowledge": {"action": "search", "query": "test"},
    "compare_papers": {"paper_keys": ["__nope_a__", "__nope_b__"]},
    "web_fetch": {"url": "example.com"},
    "read_file": {"path": "__READFILE__"},
    "write_file": {"path": "__WRITEFILE__", "content": "smoke"},
    "read_project_file": {"path": "x.txt"},
    "write_project_file": {"path": "x.txt", "content": "smoke"},
    "run_project_script": {"path": "x.py"},
    "create_document": {"title": "SMOKE_DOC_DELETE_ME", "content": "hi", "language": "text"},
    "edit_document": {"edits": [{"find": "a", "replace": "b"}]},
    "suggest_document": {"suggestions": [{"find": "a", "replace": "b", "reason": "x"}]},
    "update_document": {"content": "smoke"},
    "search_chats": {"query": "test"},
    "chat_with_model": {"model": "__nonexistent_model__", "message": "hi"},
    "create_session": {"name": "SMOKE_SESS_DELETE_ME", "model": "__nonexistent_model__"},
    "list_sessions": {},
    "send_to_session": {"session_id": "__nonexistent__", "message": "hi"},
    "pipeline": {"steps": [{"model": "__nonexistent_model__", "instruction": "hi"}]},
    "manage_session": {"action": "list"},
    "manage_memory": {"action": "list"},
    "list_models": {},
    "ui_control": {"action": "get_toggles"},
    "manage_tasks": {"action": "list"},
    "manage_calendar": {"action": "list_calendars"},
    "manage_notes": {"action": "list"},
    "api_call": {"integration": "__nonexistent__", "method": "GET", "path": "/x"},
    "ask_teacher": {"model": "__nonexistent_model__", "problem": "smoke"},
    "manage_skills": {"action": "list"},
    "manage_endpoints": {"action": "list"},
    "manage_mcp": {"action": "list"},
    "manage_webhooks": {"action": "list"},
    "manage_tokens": {"action": "list"},
    "manage_documents": {"action": "list"},
    "manage_settings": {"action": "list"},
    "download_model": {"repo_id": ""},
    "serve_model": {"repo_id": "", "cmd": ""},
    "list_served_models": {},
    "stop_served_model": {"session_id": "__nonexistent__"},
    "list_downloads": {},
    "cancel_download": {"session_id": "__nonexistent__"},
    "search_hf_models": {"query": "qwen", "limit": 3},
    "list_cached_models": {},
    "list_serve_presets": {},
    "serve_preset": {"name": "__nonexistent_preset__"},
    "adopt_served_model": {"tmux_session": "__nonexistent__", "model": "x"},
    "list_cookbook_servers": {},
    "edit_image": {"image_id": "__nonexistent__", "action": "upscale"},
    "trigger_research": {"topic": ""},
    "app_api": {"action": "endpoints", "filter": "cookbook"},
    # not in FUNCTION_TOOL_SCHEMAS — build ToolBlock directly
    "generate_image": {"prompt": ""},
    "manage_research": {"action": "list"},
}

# tools whose exit_code==1 error is EXPECTED (env-dependent), so a clean
# error still counts as "wired" not "fail" (already default), but we tag them.
NEEDS_SERVER = {"download_model", "serve_model", "list_served_models",
                "stop_served_model", "list_downloads", "cancel_download",
                "list_serve_presets", "serve_preset", "adopt_served_model",
                "list_cookbook_servers", "trigger_research", "manage_research",
                "app_api", "edit_image", "list_cached_models"}
NEEDS_MODEL = {"chat_with_model", "ask_teacher", "pipeline", "create_session",
               "web_search", "web_fetch", "search_hf_models"}


def build_block(name):
    args = BENIGN.get(name, {})
    if name in ("read_file", "write_file"):
        import tempfile, os
        from src.constants import DATA_DIR
        p = os.path.join(DATA_DIR, "_smoke_rw.txt")
        if name == "write_file":
            args = {"path": p, "content": "smoke"}
        else:
            with open(p, "w") as f:
                f.write("smoke")
            args = {"path": p}
    # manage_research isn't in schemas -> ToolBlock directly (JSON content)
    if name == "manage_research":
        return ToolBlock("manage_research", json.dumps(args))
    blk = function_call_to_tool_block(name, json.dumps(args))
    return blk


async def run_one(name):
    try:
        blk = build_block(name)
        if blk is None:
            return name, "FAIL", "function_call_to_tool_block returned None"
        desc, result = await asyncio.wait_for(
            execute_tool_block(blk, session_id=None, owner=OWNER),
            timeout=PER_TOOL_TIMEOUT,
        )
        if not isinstance(result, dict):
            return name, "FAIL", f"non-dict result: {type(result)}"
        ec = result.get("exit_code")
        if "Unknown tool type" in str(result.get("error", "")):
            return name, "FAIL", result.get("error")
        if ec == 0:
            out = str(result.get("output", result.get("results", result.get("response", ""))))
            return name, "PASS", out[:120].replace("\n", " ")
        err = str(result.get("error", result))[:160].replace("\n", " ")
        return name, "WIRED", err
    except asyncio.TimeoutError:
        return name, "FAIL", f"timeout>{PER_TOOL_TIMEOUT}s"
    except Exception as e:
        return name, "FAIL", f"{type(e).__name__}: {e}\n" + traceback.format_exc(limit=3)


async def main():
    names = sorted(TOOL_TAGS)
    results = []
    for n in names:
        results.append(await run_one(n))
    # cleanup created doc/session
    print("\n==== SMOKE RESULTS ({} commands) ====".format(len(results)))
    by = {"PASS": [], "WIRED": [], "FAIL": []}
    for name, cat, msg in results:
        by[cat].append((name, msg))
        print(f"[{cat:5}] {name:22} {msg}")
    print("\n==== SUMMARY ====")
    print("PASS :", len(by["PASS"]))
    print("WIRED:", len(by["WIRED"]))
    print("FAIL :", len(by["FAIL"]))
    if by["FAIL"]:
        print("\nFAILURES:")
        for name, msg in by["FAIL"]:
            print(f"  - {name}: {msg}")


if __name__ == "__main__":
    asyncio.run(main())
