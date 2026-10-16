"""Creates one fresh workspace per eval task.

    python make_workspaces.py OUT_ROOT --python /path/to/venv/bin/python

Each workspace gets TASK.md (prompt + common rules), the AGENTS.md shipped in
the installed wheel (``observa.agent_agents_template_path()``), and the task's
deterministic input files. T09's ``existing_run/`` is produced with the given
interpreter's installed Observa.
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tasks as T  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--python", required=True)
    a = ap.parse_args()
    agents = subprocess.check_output(
        [a.python, "-c", "import observa;print(observa.agent_agents_template_path())"], text=True).strip()
    os.makedirs(a.out, exist_ok=False)
    for tid in T.TASK_IDS:
        ws = os.path.join(a.out, tid)
        os.makedirs(ws)
        shutil.copy(agents, os.path.join(ws, "AGENTS.md"))
        with open(os.path.join(ws, "TASK.md"), "w") as fh:
            fh.write(T.PROMPTS[tid] + T.COMMON_RULES)
        short = tid.split("_")[0]
        if short == "T03":
            bars, preds = T.data_T03()
            T.write_csv(os.path.join(ws, "bars.csv"), bars)
            with open(os.path.join(ws, "predictions.csv"), "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=["timestamp", "prediction"])
                w.writeheader()
                w.writerows(preds)
        elif short == "T04":
            T.write_csv(os.path.join(ws, "bars_1m.csv"), T.data_T04())
        elif short == "T05":
            T.write_csv(os.path.join(ws, "bars.csv"), T.data_T05())
            with open(os.path.join(ws, "broken_strategy.py"), "w") as fh:
                fh.write(T.T05_BROKEN)
        elif short == "T06":
            T.write_csv(os.path.join(ws, "btc_h1.csv"), T.data_T06())
            with open(os.path.join(ws, "strategy.py"), "w") as fh:
                fh.write(T.T06_STRATEGY)
            with open(os.path.join(ws, "run_it.py"), "w") as fh:
                fh.write(T.T06_RUN)
        elif short == "T07":
            T.write_csv(os.path.join(ws, "bars_5m.csv"), T.data_T07())
            with open(os.path.join(ws, "strategy.py"), "w") as fh:
                fh.write(T.T07_STRATEGY)
        elif short == "T09":
            T.write_csv(os.path.join(ws, "_bars.csv"), T.random_walk(400, seed=909))
            with open(os.path.join(ws, "_busy.py"), "w") as fh:
                fh.write(T.T09_STRATEGY)
            subprocess.check_call([a.python, "-c", (
                "import sys; sys.path.insert(0, '.'); import observa; from _busy import Busy; "
                "observa.run(Busy(), '_bars.csv', config=observa.Config(interval='1h'), output='existing_run')")],
                cwd=ws)
            os.remove(os.path.join(ws, "_busy.py"))
            os.remove(os.path.join(ws, "_bars.csv"))
            shutil.rmtree(os.path.join(ws, "__pycache__"), ignore_errors=True)
        else:
            data = {"T01": T.data_T01, "T02": T.data_T02, "T08": T.data_T08, "T10": T.data_T10}[short]()
            T.write_csv(os.path.join(ws, "bars.csv"), data)
    print("created", len(T.TASK_IDS), "workspaces in", a.out)


if __name__ == "__main__":
    main()
