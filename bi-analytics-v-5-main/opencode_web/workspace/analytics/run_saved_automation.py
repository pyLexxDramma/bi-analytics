from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scripts-dir",
        default="/workspace/analytics/generated",
        help="Папка с сохраненными скриптами",
    )
    parser.add_argument(
        "--pattern",
        default="*.py",
        help="Маска файлов для запуска",
    )
    args = parser.parse_args()

    scripts_dir = Path(args.scripts_dir)
    scripts = sorted(scripts_dir.glob(args.pattern))
    if not scripts:
        print("No scripts found")
        return

    for script_path in scripts:
        print(f"Running: {script_path}")
        result = subprocess.run(
            ["python", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"Exit code: {result.returncode}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)


if __name__ == "__main__":
    main()
