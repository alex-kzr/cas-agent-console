"""Fixed offline regression participant: no sockets/native children/SDK execution."""

import importlib.util
import json
import site
import sys
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
root = Path(sys.argv[1]).resolve()
assert root.is_relative_to(HERE) and root.name.startswith("tmp")
plan = json.loads((root / "peer-plan.json").read_text())
for path in plan["site_paths"]:
    assert Path(path).is_dir() and Path(path).name in {"site-packages", "dist-packages"}
    site.addsitedir(path)
spec = importlib.util.spec_from_file_location("candidate_peer", Path(sys.argv[2]))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
peer = module.WorkingSessions(root, root=Path(plan["project_root"]))
save = peer.save


def held(record):
    (root / "peer-ready").write_text("locked")
    deadline = time.monotonic() + 4
    while not (root / "peer-release").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("PEER_RELEASE_TIMEOUT")
        time.sleep(0.01)
    save(record)


peer.save = held
with (
    patch("subprocess.Popen", side_effect=AssertionError("NO_CHILD_PROCESS")),
    patch("socket.socket", side_effect=AssertionError("NO_SOCKET")),
):
    peer.request(plan["session_id"], plan["plan_hash"])
print("OFFLINE_PEER_DONE")
