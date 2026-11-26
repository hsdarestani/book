#!/usr/bin/env bash

fail_release() {
  printf '%s\n' "$1" >&2
  return 1
}

django_at() {
  local directory="$1"
  shift
  runuser -u aestheticbook -- bash -c '
    set -ae
    source "$1"
    cd "$2"
    shift 2
    exec /opt/aesthetic-book/venv/bin/python manage.py "$@"
  ' bash "$env_file" "$directory" "$@"
}

prepare_candidate() {
  django_at "$stage" check || return 1
  django_at "$stage" shell < "$tools_dir/check_phase_a_migration.py" || return 1
  django_at "$stage" migrate booking 0032_appointment_treatment_duration --noinput || return 1
  django_at "$stage" shell < "$tools_dir/book_phase_a_smoke.py"
}

collect_release_static() {
  django_at "$app" collectstatic --noinput
}

restart_book() {
  systemctl restart aesthetic-book
}

check_book() {
  local attempt
  for attempt in {1..12}; do
    if systemctl is-active --quiet aesthetic-book &&
      curl --silent --fail --max-time 5 http://127.0.0.1:8017/api/health/ >/dev/null &&
      curl --silent --fail --max-time 8 https://book.a-esthetic.de/api/health/ >/dev/null; then
      return
    fi
    sleep 2
  done
  fail_release 'Book health check failed.'
}

check_live_calendar_asset() {
  curl --compressed --silent --fail --max-time 10 \
    "https://book.a-esthetic.de/static/booking/admin-calendar-plus.js?release=$target" |
    cmp -s "$app/static/booking/admin-calendar-plus.js" -
}

# Fingerprints stay in a root-only rollback directory.
capture_preserved() {
  local path
  stat -c '%a %u %g' "$env_file"
  sha256sum "$env_file"
  for path in "${preserved_assets[@]}"; do
    test -f "$app/$path" || return 1
    sha256sum "$app/$path"
    if [[ -f "$app/staticfiles/${path#static/}" ]]; then
      sha256sum "$app/staticfiles/${path#static/}"
    fi
  done
}

restore_checkout() {
  local checkout="$1"
  if [[ -n "$original_branch" ]]; then
    [[ "$(git -C "$app" rev-parse "$original_branch")" == "$checkout" ]] || return 1
    git -C "$app" switch --no-overwrite-ignore "$original_branch" >&2 || return 1
  else
    git -C "$app" switch --no-overwrite-ignore --detach "$checkout" >&2 || return 1
  fi
  # The exact preexisting native sources are restored only on rollback.
  local path
  for path in booking/mobile_staff_api.py booking/management/commands/reconcile_mobile_cancellations.py booking/simplybook_writeback.py; do
    if [[ -f "$snapshot/source-collisions/$path" ]]; then
      cp -a "$snapshot/source-collisions/$path" "$app/$path" || return 1
      cmp -s "$snapshot/source-collisions/$path" "$app/$path" || return 1
    fi
  done
  # Move the failed tree aside before restoring the saved static tree.
  mv -- "$app/staticfiles" "$snapshot/staticfiles-failed" || return 1
  cp -a -- "$snapshot/staticfiles" "$app/staticfiles" || return 1
  diff -qr -- "$snapshot/staticfiles" "$app/staticfiles" >/dev/null || return 1
  [[ "$(git -C "$app" rev-parse HEAD)" == "$checkout" ]] || return 1
  capture_preserved > "$snapshot/restored-preserved" || return 1
  cmp -s "$snapshot/preserved" "$snapshot/restored-preserved" || return 1
  restart_book || return 1
  check_book
}

verify_release_scope() {
  local path
  while IFS= read -r path; do
    case "$path" in
      .github/workflows/verify-mobile-booking-recovery.yml|docs/qa/AESTHETIC_REMEDIATION.md|\
      booking/admin_views.py|booking/api.py|booking/app_admin_api.py|booking/calendar_admin_api.py|\
      booking/clinical_time.py|booking/doctor_views.py|booking/emails.py|\
      booking/migrations/0032_appointment_treatment_duration.py|booking/mobile_api.py|\
      booking/models.py|booking/notifications.py|booking/services.py|booking/simplybook_outbound.py|\
      booking/test_booking_reservation_duration.py|booking/test_clinical_time.py|booking/test_doctor_read_only.py|booking/views.py|\
      static/booking/admin-calendar-plus.js|static/booking/admin.js|templates/booking/dashboard.html) ;;
      *) fail_release 'The release contains changes outside the Phase A allowlist.' ;;
    esac
  done <<< "$1"
}

release_book() (
  set -euo pipefail
  app="$1" env_file="$2" backups="$3" tools_dir="$4" baseline="$5" target="$6"
  cutover=0
  preserved_assets=(
    static/booking/calendar-mobile-sticky-day-header-v1.css
    static/booking/calendar-sunday-closed-v1.css
    static/booking/calendar-week-strip-swipe-v1.js
  )

  install -d -m 0700 "$backups"
  exec 9>"$backups/release.lock"
  flock -n 9
  checkout="$(git -C "$app" rev-parse HEAD)"
  [[ "$checkout" == "$baseline" ]] || fail_release 'Unexpected Book baseline. No release applied.'
  [[ -z "$(git -C "$app" status --porcelain --untracked-files=no)" ]] ||
    fail_release 'Production has tracked modifications. No release applied.'
  [[ -d "$app/staticfiles" && ! -L "$app/staticfiles" ]]
  [[ -f "$env_file" && ! -L "$env_file" ]]
  git -C "$app" merge-base --is-ancestor "$baseline" "$target"
  changes="$(git -C "$app" diff --name-only "$baseline" "$target")"
  verify_release_scope "$changes"
  check_book

  snapshot="$(mktemp -d "$backups/${release_id:-phase-a}.XXXXXXXX")"
  stage="$(mktemp -d "$(dirname "$app")/.${release_id:-phase-a}-stage.XXXXXXXX")"
  original_branch="$(git -C "$app" symbolic-ref --quiet --short HEAD || true)"
  trap '
    result=$?
    if (( result != 0 && cutover )); then
      if restore_checkout "$checkout"; then
        printf "BOOK_ROLLBACK_VERIFIED=%s\n" "$checkout"
      else
        printf "BOOK_ROLLBACK_FAILED=%s\n" "$checkout" >&2
        result=2
      fi
    fi
    git -C "$app" worktree remove "$stage" >/dev/null 2>&1 || true
    exit "$result"
  ' EXIT
  capture_preserved > "$snapshot/preserved"
  cp -a -- "$app/staticfiles" "$snapshot/staticfiles"
  diff -qr -- "$app/staticfiles" "$snapshot/staticfiles" >/dev/null
  printf '%s\n' "$checkout" > "$snapshot/previous-revision"

  git -C "$app" worktree add --detach "$stage" "$target"
  chmod 0755 "$stage"
  if ! prepare_candidate >"$snapshot/prepare.log" 2>&1; then
    fail_release 'Candidate migration or synthetic calendar check failed before cutover.'
  fi

  # A nullable column can remain applied if the old checkout is restored.
  cutover=1
  # Previous native code was left untracked by an older release. Preserve the
  # exact original bytes and accept only reviewed content, never unknown files.
  local path blob target_blob
  for path in booking/mobile_staff_api.py booking/management/commands/reconcile_mobile_cancellations.py booking/simplybook_writeback.py; do
    if [[ -e "$app/$path" ]] && ! git -C "$app" ls-files --error-unmatch "$path" >/dev/null 2>&1; then
      [[ -f "$app/$path" && ! -L "$app/$path" ]] || fail_release 'Unexpected native source type.'
      target_blob=$(git -C "$app" rev-parse "$target:$path")
      blob=$(git -C "$app" hash-object "$app/$path")
      if [[ "$blob" != "$target_blob" && ! ( "$path" == booking/mobile_staff_api.py && "$blob" == fd16eff1395fe69a9675011348bfc86cc137d336 ) && ! ( "$path" == booking/simplybook_writeback.py && "$blob" == a3d8ce8a2e0c20d0859b1ca1f5ea6fa41713dcb7 ) ]]; then
        fail_release 'Unexpected untracked source bytes; nothing overwritten.'
      fi
      mkdir -p "$snapshot/source-collisions/$(dirname "$path")"
      mv -- "$app/$path" "$snapshot/source-collisions/$path"
    fi
  done
  git -C "$app" switch --no-overwrite-ignore --detach "$target"
  if ! collect_release_static >"$snapshot/static.log" 2>&1; then
    fail_release 'Static collection failed.'
  fi
  capture_preserved > "$snapshot/release-preserved"
  cmp -s "$snapshot/preserved" "$snapshot/release-preserved"
  restart_book
  check_book
  check_live_calendar_asset
  if ! django_at "$app" shell < "$tools_dir/book_phase_a_smoke.py" >"$snapshot/smoke.log" 2>&1; then
    fail_release 'Deployed authenticated synthetic calendar check failed.'
  fi
  [[ "$(git -C "$app" rev-parse HEAD)" == "$target" ]]
  printf 'BOOK_DEPLOYED=%s\nBOOK_AUTHENTICATED_SYNTHETIC_CALENDAR=18:30/19:15/19:25\n' "$target"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  release_book /opt/aesthetic-book/app /etc/aesthetic-book.env \
    /opt/aesthetic-book/remediation-rollbacks "$(dirname "$0")" "$@"
fi
