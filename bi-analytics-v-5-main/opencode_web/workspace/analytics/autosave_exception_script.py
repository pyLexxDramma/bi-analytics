from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path


def build_template(error_text: str, title: str) -> str:
    return f'''"""
Auto-saved script template
Title: {title}
Created at: {datetime.now(UTC).isoformat()}
Error context:
{error_text}
"""

from pathlib import Path
import pandas as pd


def main() -> None:
    # TODO: Replace with reusable logic based on the captured exception context.
    csv_path = Path("/workspace/sample_budget_data.csv")
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    print(df.head(10))


if __name__ == "__main__":
    main()
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True, help="Короткое название кейса")
    parser.add_argument("--error", required=True, help="Текст исключения")
    parser.add_argument(
        "--out-dir",
        default="/workspace/analytics/generated",
        help="Папка для авто-сохраненных скриптов",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fingerprint = hashlib.sha1(args.error.encode("utf-8")).hexdigest()[:10]
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_name = f"{timestamp}_{fingerprint}_{args.title.lower().replace(' ', '_')}.py"
    target_path = out_dir / file_name

    target_path.write_text(build_template(args.error, args.title), encoding="utf-8")
    print(str(target_path))


if __name__ == "__main__":
    main()
