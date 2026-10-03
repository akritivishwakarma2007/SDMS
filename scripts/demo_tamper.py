"""Demo step 3: run a simulation, tamper with one DB row, show verify() flagging the exact record."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import json
from sdms.simulator.virtual_box import run_simulation

res, led = run_simulation(60, seed=5)
print("before tamper:", led.verify().as_dict())
led._conn.execute("DROP TRIGGER events_no_update")          # attacker with DB admin rights
row = led.rows()[19]; items = json.loads(row["items"])
if items: items[0]["label"] = "500"
led._conn.execute("UPDATE events SET items=? WHERE seq=?", (json.dumps(items, sort_keys=True, separators=(",", ":")), row["seq"]))
print("after tamper: ", led.verify().as_dict())
