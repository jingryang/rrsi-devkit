# Copyright 2026 The rrsi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Sequential driver: baseline + calibration if missing, then rounds t..T-1.

A round is settled once the frontier trajectory has an entry for t+1.
`touch runs/<domain>/STOP` stops after the current round. Consecutive
infrastructure failures stop the driver so a broken environment cannot burn
the whole budget.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

MAX_CONSECUTIVE_INFRA = 3
# Wait between retries of the same round. A round usually fails on a transient
# gateway fault; hammering it immediately just repeats the failure.
RETRY_BACKOFF_SEC = 300


def settled_rounds(frontier_path: Path) -> int:
    if not frontier_path.exists():
        return -1
    fr = json.loads(frontier_path.read_text())
    return len(fr["trajectory"]) - 1          # trajectory has entries 0..settled


def drive(entry: Path, domain: str, runs_dir: Path, T: int, start: int = 0,
          extra_args: list[str] | None = None) -> None:
    run_dir = runs_dir / domain
    fr = run_dir / "frontier.json"
    stop = run_dir / "STOP"
    logs = run_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    base_args = [sys.executable, str(entry), "--domain", domain,
                 "--runs", str(runs_dir)] + list(extra_args or [])
    if not fr.exists():
        print(f"[driver:{domain}] baseline + calibrate", flush=True)
        with open(logs / "baseline.log", "a") as lf:
            r = subprocess.run(base_args + ["baseline"], stdout=lf, stderr=subprocess.STDOUT)
        if r.returncode != 0 or not fr.exists():
            print(f"[driver:{domain}] baseline failed (rc={r.returncode})")
            sys.exit(1)
    if not (run_dir / "calibration.json").exists():
        with open(logs / "calibrate.log", "a") as lf:
            subprocess.run(base_args + ["calibrate"], stdout=lf, stderr=subprocess.STDOUT)
    infra = 0
    for t in range(start, T):
        # A round that fails is retried (up to MAX_CONSECUTIVE_INFRA times)
        # rather than skipped: the loop below only advances t once the frontier
        # has an entry for t+1, which is what "settled" means.
        while settled_rounds(fr) < t + 1:
            if stop.exists():
                print(f"[driver:{domain}] STOP present; exiting", flush=True)
                return
            log = logs / f"r{t}.log"
            print(f"[driver:{domain}] === round {t} ({time.strftime('%H:%M:%S')}) "
                  f"-> {log}", flush=True)
            with open(log, "a") as lf:
                r = subprocess.run(base_args + ["round", "--t", str(t)],
                                   stdout=lf, stderr=subprocess.STDOUT)
            if r.returncode == 0 and settled_rounds(fr) >= t + 1:
                infra = 0
                b = json.loads(fr.read_text())["incumbent"]
                print(f"[driver:{domain}]   incumbent t={b['t']} {b['commit']} "
                      f"S={b['S']:.4f}", flush=True)
                break
            infra += 1
            print(f"[driver:{domain}] round {t} did not settle (rc={r.returncode}, "
                  f"{infra}/{MAX_CONSECUTIVE_INFRA}); retrying in "
                  f"{RETRY_BACKOFF_SEC}s", flush=True)
            if infra >= MAX_CONSECUTIVE_INFRA:
                print(f"[driver:{domain}] too many consecutive failures; stopping "
                      f"at round {t} (the frontier is untouched, rerun to resume)")
                sys.exit(1)
            time.sleep(RETRY_BACKOFF_SEC)
        else:
            print(f"[driver:{domain}] round {t} already settled", flush=True)
    print(f"[driver:{domain}] all {T} round(s) settled", flush=True)
