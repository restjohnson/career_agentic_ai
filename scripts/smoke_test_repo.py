from pathlib import Path
import sys
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.supabase_repo import SupabaseRepo


repo = SupabaseRepo()
sid = repo.create_session()
rid = repo.create_run(sid, "Software Engineer")
repo.append_run_state(sid, rid, "role_intake", {"ok": True}, contains_free_text=False)
latest = repo.get_latest_run_state(sid, rid)

print("session_id:", sid)
print("run_id:", rid)
print("latest:", latest["step"], latest["state"])
