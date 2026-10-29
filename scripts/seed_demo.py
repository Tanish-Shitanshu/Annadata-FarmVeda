"""Fill an empty database with the demo world (see core/demo.py).

    python scripts/seed_demo.py            # uses FARMVEDA_DB_PATH, or ./farmveda.db
    streamlit run app.py

Sign in as ravi@example.com (farmer) or asha@example.com (consumer); password demo-pass-123.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import demo  # noqa: E402


def main() -> None:
    try:
        demo.load_demo()
    except RuntimeError as exc:
        sys.exit(f"{exc} Point FARMVEDA_DB_PATH at an empty file to seed a fresh demo.")
    print(f"Demo data ready. Sign in as {demo.DEMO_FARMER_EMAIL} (farmer) or {demo.DEMO_CONSUMER_EMAIL} "
          f"(consumer), password {demo.DEMO_PASSWORD}.")


if __name__ == "__main__":
    main()
