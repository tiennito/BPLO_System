"""Run the annual permit renewal daily status/reminder job."""

from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import load_env
from backend.notification_service import NotificationServiceMixin
from backend.renewal_service import RenewalServiceMixin
from backend.supabase_client import SupabaseClientMixin


class RenewalJobRunner(RenewalServiceMixin, NotificationServiceMixin, SupabaseClientMixin):
    client_address = None
    headers = {}


def main():
    load_env()
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip() or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not supabase_url or not service_key:
        print(json.dumps({"error": "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required."}))
        return 2

    runner = RenewalJobRunner()
    config = {
        "supabase_url": supabase_url,
        "supabase_service_key": service_key,
        "actor": {"id": None, "email": "system@bplo.local", "app_metadata": {"role": "system"}},
    }
    result = runner.process_daily_renewals(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
