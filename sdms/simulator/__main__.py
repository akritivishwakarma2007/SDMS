import argparse, json
from .virtual_box import run_simulation

ap = argparse.ArgumentParser(description="Run the virtual donation box")
ap.add_argument("--drops", type=int, default=200)
ap.add_argument("--seed", type=int, default=1)
a = ap.parse_args()
res, _ = run_simulation(a.drops, a.seed)
print(json.dumps(res.summary(), indent=2, default=str))
