"""Second-pass smoke: init session/memory managers in-process (no HTTP server)
and exercise the manager-dependent READ-ONLY model commands end-to-end."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OWNER = "kincaidr"
from src.constants import DATA_DIR, SESSIONS_FILE
from src.memory import MemoryManager
from core.session_manager import SessionManager
import src.ai_interaction as ai

sm = SessionManager(SESSIONS_FILE)
mm = MemoryManager(DATA_DIR)
ai.set_session_manager(sm)
try:
    from core.models import set_session_manager as core_set_sm
    core_set_sm(sm)
except Exception as e:
    print("core set_sm note:", e)
ai.set_memory_manager(mm)

from src.agent_tools import ToolBlock
from src.tool_execution import execute_tool_block

CASES = {
    "list_sessions": "",
    "manage_session": "list",
    "manage_memory": "list",
    "send_to_session": "__nonexistent__\nhi",
}

async def main():
    for tool, content in CASES.items():
        try:
            desc, res = await asyncio.wait_for(
                execute_tool_block(ToolBlock(tool, content), session_id=None, owner=OWNER),
                timeout=20)
            ec = res.get("exit_code")
            body = str(res.get("results", res.get("response", res.get("output", res.get("error", res)))))
            print(f"[{tool}] ec={ec} :: {body[:160].replace(chr(10),' ')}")
        except Exception as e:
            print(f"[{tool}] EXC {type(e).__name__}: {e}")

asyncio.run(main())
