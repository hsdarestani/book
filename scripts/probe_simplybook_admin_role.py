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
                start=(sample.get("start_date") or "")[:10]
                if len(start)==10 and start[4]=='-':
                    matrix=rpc("https://user-api.simplybook.me/admin","getStartTimeMatrix",
                        [start,start,int(sample["event_id"]),int(sample["unit_id"]),1,
                         int(sample["id"]),[]],headers)
                    print("AVAILABILITY_SHAPE root_type="+type(matrix).__name__ +
                        " root_keys="+(",".join(sorted(matrix.keys())) if isinstance(matrix,dict) else "")+
                        " day_type="+type(matrix.get(start)).__name__ if isinstance(matrix,dict) else
                        "AVAILABILITY_SHAPE root_type="+type(matrix).__name__)
        else:
            print("SOURCE_SHAPE no_upcoming_sample=yes")
        # Catalog is non-patient metadata. Do not emit any contact data.
        units=rpc("https://user-api.simplybook.me/admin","getUnitList",[False,True],headers)
        events=rpc("https://user-api.simplybook.me/admin","getEventList",[False,True,None,""],headers)
        tz=rpc("https://user-api.simplybook.me/admin","getCompanyTimezoneOffset",[],headers)
        print("SYNC_TIMEZONE="+str(tz.get("timezone","unknown") if isinstance(tz,dict) else "unknown"))
        for unit in units or []:
            if isinstance(unit,dict):
                print("SYNC_UNIT="+json.dumps({k:unit.get(k) for k in ("id","name","is_active")},ensure_ascii=False))
        for event in events or []:
            if isinstance(event,dict):
                print("SYNC_EVENT="+json.dumps({k:event.get(k) for k in ("id","name","is_active","duration","buffertime_before","buffertime_after","unit_map")},ensure_ascii=False))
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
