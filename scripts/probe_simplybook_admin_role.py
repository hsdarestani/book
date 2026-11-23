"""Read-only SimplyBook Admin API capability probe.

Logs no company login, token, client, booking, or patient information.
Never calls a method that mutates SimplyBook.
"""
import json
import os
import urllib.error
import urllib.request


def rpc(url, method, params, headers=None):
    raw = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(
        url, data=raw, method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("RPC HTTP " + str(exc.code)) from None
    except urllib.error.URLError:
        raise RuntimeError("SimplyBook RPC network unavailable") from None
    if payload.get("error"):
        err = payload["error"] or {}
        raise RuntimeError("RPC error code " + str(err.get("code") or "unknown")) from None
    return payload.get("result")


def main():
    company = (os.getenv("SIMPLYBOOK_COMPANY_LOGIN") or "").strip()
    user = (os.getenv("SIMPLYBOOK_USER_LOGIN") or "").strip()
    key = (os.getenv("SIMPLYBOOK_API_USER_KEY") or
           os.getenv("SIMPLYBOOK_USER_PASSWORD") or "").strip()
    if not all([company, user, key]):
        print("CAPABILITY_RESULT credential_config=missing role=unverified write_access=not_tested")
        return 2
    try:
        token = rpc("https://user-api.simplybook.me/login", "getUserToken", [company, user, key])
        if not token:
            raise RuntimeError("empty token")
        headers = {"X-Company-Login": company, "X-User-Token": token}
        details = rpc("https://user-api.simplybook.me/admin", "getCurrentUserDetails", [], headers)
        group = (details.get("group") or "unavailable") if isinstance(details, dict) else "unavailable"
        if group not in {"admin", "shop_user", "station_user", "viewer", "reseller_company_admin"}:
            group = "unknown"
        from datetime import datetime, timedelta
        today = datetime.now().date()
        bookings = rpc("https://user-api.simplybook.me/admin", "getBookings",
            [{"date_from": today.isoformat(), "date_to": (today+timedelta(days=45)).isoformat(),
              "booking_type":"all", "order":"date_start_asc"}],headers)
        if isinstance(bookings,list) and bookings:
            sample=next((row for row in bookings if isinstance(row,dict) and row.get("id")),None)
            if sample:
                detail=rpc("https://user-api.simplybook.me/admin","getBookingDetails",[int(sample["id"])],headers)
                detail_keys=sorted(detail.keys()) if isinstance(detail,dict) else []
                print("SOURCE_SHAPE booking_row_keys=" + ",".join(sorted(sample.keys())) +
                     " details_keys=" + ",".join(detail_keys) +
                     " detail_type=" + type(detail).__name__)
        else:
            print("SOURCE_SHAPE no_upcoming_sample=yes")
        print("CAPABILITY_RESULT credential_config=present authenticated=yes admin_api=yes "
              "role=" + group + " full_admin=" + ("yes" if group == "admin" else "no") +
              " write_access=not_tested remote_changes=none")
        return 0
    except RuntimeError as exc:
        print("CAPABILITY_RESULT credential_config=present "
              "authenticated=unverified role=unverified "
              "write_access=not_tested remote_changes=none error=" + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
