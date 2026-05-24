"""
Standalone entry-point for the Finance mini-app.
Run: python -m finance.finance_launcher   OR   python finance/finance_launcher.py
"""
import os
import sys
from pathlib import Path

# Allow `finance` to be importable when run directly from repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = int(os.environ.get("FINANCE_PORT", "8001"))


def main() -> None:
    import uvicorn

    print(f"[Finance] Starting on http://127.0.0.1:{PORT}")
    uvicorn.run(
        "finance.app.main:app",
        host="127.0.0.1",
        port=PORT,
        log_level="warning",
        reload=False,
    )


if __name__ == "__main__":
    main()
