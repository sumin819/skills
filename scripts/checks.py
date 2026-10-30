#!/usr/bin/env python3
"""Run local verification commands and keep per-run evidence. Python 3.9+."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def read_checks(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"checks"}:
        raise ValueError("Config must contain only a checks array")
    checks = config["checks"]
    if not isinstance(checks, list) or not checks:
        raise ValueError("checks must be a nonempty array")
    names = set()
    for item in checks:
        if not isinstance(item, dict) or set(item) - {"name", "argv", "timeout", "expect_exit", "stdout_contains"}:
            raise ValueError("Invalid check fields")
        name, argv = item.get("name"), item.get("argv")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("Each check needs a unique, nonempty name")
        names.add(name)
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x and "\x00" not in x for x in argv):
            raise ValueError(f"{name}: argv must be a nonempty string array")
        timeout = item.get("timeout", 60)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(f"{name}: timeout must be positive and finite")
        if type(item.get("expect_exit", 0)) is not int:
            raise ValueError(f"{name}: expect_exit must be an integer")
        contains = item.get("stdout_contains", [])
        if not isinstance(contains, list) or not all(isinstance(x, str) and x for x in contains):
            raise ValueError(f"{name}: stdout_contains must be an array of nonempty strings")
    return checks


def stop_process(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    process.wait()


def run_check(item, root, output, index):
    argv = [sys.executable if i == 0 and arg == "{python}" else arg for i, arg in enumerate(item["argv"])]
    stdout_path = output / f"{index:02d}.stdout.log"
    stderr_path = output / f"{index:02d}.stderr.log"
    started = time.monotonic()
    code, error, timed_out = None, None, False
    process = None
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        try:
            process = subprocess.Popen(argv, cwd=root, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                       start_new_session=(os.name == "posix"))
            code = process.wait(timeout=item.get("timeout", 60))
        except subprocess.TimeoutExpired:
            timed_out = True
            stop_process(process)
            code = process.returncode
        except OSError as exc:
            error = str(exc)
        except KeyboardInterrupt:
            if process is not None:
                stop_process(process)
            raise
    # Stream logs instead of retaining unbounded subprocess output in memory.
    needles = item.get("stdout_contains", [])
    missing = []
    for needle in needles:
        token = needle.encode("utf-8")
        found, tail = False, b""
        with stdout_path.open("rb") as stream:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                block = tail + chunk
                if token in block:
                    found = True
                    break
                tail = block[-max(len(token) - 1, 0):] if len(token) > 1 else b""
        if not found:
            missing.append(needle)
    passed = not timed_out and error is None and code == item.get("expect_exit", 0) and not missing
    return {"name": item["name"], "argv": argv, "passed": passed, "exit_code": code,
            "expected_exit": item.get("expect_exit", 0), "timeout": timed_out, "error": error,
            "missing_stdout": missing, "seconds": round(time.monotonic() - started, 3),
            "stdout": stdout_path.name, "stderr": stderr_path.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path(".runs"))
    args = parser.parse_args()
    try:
        checks = read_checks(args.config)
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("root must be a directory")
        args.output.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output.resolve()))
        results = []
        report = {"started_at": datetime.now(timezone.utc).isoformat(), "root": str(root),
                  "config": str(args.config.resolve()), "complete": False, "results": results}
        report_path = output / "report.json"
        def save():
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        save()
        try:
            for index, item in enumerate(checks, 1):
                result = run_check(item, root, output, index)
                results.append(result)
                save()
                print(f"{'PASS' if result['passed'] else 'FAIL'} {item['name']} ({result['seconds']}s)")
        except KeyboardInterrupt:
            print(f"Interrupted; incomplete report: {report_path}", file=sys.stderr)
            return 130
        report["complete"] = True
        report["passed"] = all(r["passed"] for r in results)
        save()
        print(f"Report: {report_path}")
        return 0 if report["passed"] else 1
    except (OSError, ValueError) as exc:
        print(f"Configuration or I/O error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
