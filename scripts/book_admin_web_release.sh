#!/usr/bin/env bash

source "$(dirname "$0")/book_phase_a_release.sh"
release_id=admin-web

verify_release_scope() {
  printf '%s\n' "$1" | cmp -s "$tools_dir/book_admin_web_scope.txt" - ||
    fail_release 'The candidate differs from the approved admin web release scope.'
}

prepare_candidate() {
  django_at "$stage" check || return 1
  django_at "$stage" shell < "$tools_dir/check_admin_web_schema.py" || return 1
  django_at "$stage" shell < "$tools_dir/book_phase_a_smoke.py"
}

check_live_calendar_asset() {
  local path
  for path in clinic-web-polish-v2.css calendar-mobile-sticky-heading-v2.css; do
    curl --compressed --silent --fail --max-time 10 \
      "https://book.a-esthetic.de/static/booking/$path?release=$target" |
      cmp -s "$app/static/booking/$path" - || return 1
  done
}

release_book /opt/aesthetic-book/app /etc/aesthetic-book.env \
  /opt/aesthetic-book/remediation-rollbacks "$(dirname "$0")" "$@"
