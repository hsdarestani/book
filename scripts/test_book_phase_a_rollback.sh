#!/usr/bin/env bash
set -euo pipefail
tools_dir="$(cd "$(dirname "$0")" && pwd)"
source "$tools_dir/book_phase_a_release.sh"
temp="$(mktemp -d)"
trap 'rm -rf -- "$temp"' EXIT

fixture="$temp/app"
git init -q -b main "$fixture"
git -C "$fixture" config user.name Release-QA
git -C "$fixture" config user.email qa@example.invalid
mkdir -p "$fixture/booking" "$fixture/static/booking" "$fixture/staticfiles/booking"
printf 'baseline\n' > "$fixture/booking/services.py"
git -C "$fixture" add booking
git -C "$fixture" commit -qm baseline
baseline="$(git -C "$fixture" rev-parse HEAD)"
git -C "$fixture" switch -qc release-candidate
printf 'candidate\n' > "$fixture/booking/services.py"
printf 'prior native source\n' > "$fixture/booking/mobile_staff_api.py"
git -C "$fixture" add booking/mobile_staff_api.py
git -C "$fixture" commit -qam phase-a
target="$(git -C "$fixture" rev-parse HEAD)"
git -C "$fixture" switch -q main
printf 'prior native source\n' > "$fixture/booking/mobile_staff_api.py"
for file in calendar-mobile-sticky-day-header-v1.css calendar-sunday-closed-v1.css calendar-week-strip-swipe-v1.js; do
  printf 'preserved %s\n' "$file" > "$fixture/static/booking/$file"
  cp "$fixture/static/booking/$file" "$fixture/staticfiles/booking/$file"
done
printf old-manifest > "$fixture/staticfiles/staticfiles.json"
printf 'SETTING=synthetic-preserved\n' > "$temp/book.env"
chmod 0640 "$temp/book.env"

verify_release_scope() { [[ "$1" == $'booking/mobile_staff_api.py\nbooking/services.py' ]]; }
prepare_candidate() { test "$(cat "$stage/booking/services.py")" = candidate; }
collect_release_static() { printf candidate-manifest > "$app/staticfiles/staticfiles.json"; }
restart_book() { :; }
check_live_calendar_asset() { :; }
django_at() { :; }
check_book() {
  [[ "$(git -C "$app" rev-parse HEAD)" == "$baseline" || -f "$temp/allow-candidate" ]]
}

set +e
release_book "$fixture" "$temp/book.env" "$temp/backups" "$tools_dir" "$baseline" "$target" > "$temp/failed.log" 2>&1
result=$?
set -e
[[ "$result" == 1 ]]
grep -Fx "BOOK_ROLLBACK_VERIFIED=$baseline" "$temp/failed.log"
[[ "$(git -C "$fixture" symbolic-ref --short HEAD)" == main ]]
[[ "$(cat "$fixture/staticfiles/staticfiles.json")" == old-manifest ]]
[[ "$(cat "$fixture/booking/services.py")" == baseline ]]
[[ "$(cat "$fixture/booking/mobile_staff_api.py")" == "prior native source" ]]
! git -C "$fixture" ls-files --error-unmatch booking/mobile_staff_api.py >/dev/null 2>&1
[[ "$(stat -c '%a' "$temp/book.env")" == 640 ]]
grep -Fx 'SETTING=synthetic-preserved' "$temp/book.env"

touch "$temp/allow-candidate"
release_book "$fixture" "$temp/book.env" "$temp/backups" "$tools_dir" "$baseline" "$target" > "$temp/passed.log"
grep -Fx "BOOK_DEPLOYED=$target" "$temp/passed.log"
[[ "$(cat "$fixture/staticfiles/staticfiles.json")" == candidate-manifest ]]
[[ "$(cat "$fixture/booking/services.py")" == candidate ]]
for file in "$fixture"/static/booking/*; do
  cmp "$file" "$fixture/staticfiles/booking/${file##*/}"
done
