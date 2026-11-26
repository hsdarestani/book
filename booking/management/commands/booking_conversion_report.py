"""Internal aggregate report. No individual records, identifiers or external transmission."""
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Case, CharField, Count, Value, When
from django.utils import timezone

from booking.models import Appointment

BERLIN = ZoneInfo("Europe/Berlin")
CHANNELS = ("web", "app", "admin", "imported", "other")
STATUSES = ("new", "confirmed", "completed", "cancelled", "no_show", "other")


def aggregate_bookings(start, end):
    if end < start or (end - start).days >= 366:
        raise ValueError("Select an inclusive range of 1 to 366 days.")
    lower = datetime.combine(start, time.min, tzinfo=BERLIN)
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=BERLIN)
    qs = Appointment.objects.filter(created_at__gte=lower, created_at__lt=upper)
    qs = qs.annotate(
        channel_bucket=Case(
            When(idempotency_key__startswith="simplybook-", then=Value("imported")),
            When(idempotency_key__startswith="legacy-aesthetic-", then=Value("imported")),
            When(source="web", then=Value("web")),
            When(source="app", then=Value("app")),
            When(source="admin", then=Value("admin")),
            default=Value("other"), output_field=CharField(),
        ),
        status_bucket=Case(
            *[When(status=status, then=Value(status)) for status in STATUSES],
            default=Value("other"), output_field=CharField(),
        ),
    )
    counts = {channel: dict.fromkeys(STATUSES, 0) for channel in CHANNELS}
    for row in qs.order_by().values("channel_bucket", "status_bucket").annotate(total=Count("pk")):
        counts[row["channel_bucket"]][row["status_bucket"]] = row["total"]
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "timezone": "Europe/Berlin",
        "channels": counts,
        "online_created": sum(sum(counts[c].values()) for c in ("web", "app")),
        "online_confirmed_or_completed": sum(counts[c][s] for c in ("web", "app") for s in ("confirmed", "completed")),
        "online_pending": sum(counts[c]["new"] for c in ("web", "app")),
        "online_cancelled": sum(counts[c]["cancelled"] for c in ("web", "app")),
        "online_no_show": sum(counts[c]["no_show"] for c in ("web", "app")),
        "limitations": "Creation cohort, current statuses, not confirmation history or SEO attribution. Known imported key prefixes separated. Historical test records not independently excluded.",
    }


class Command(BaseCommand):
    help = "Return only aggregate internal appointment counts by channel and current status."

    def add_arguments(self, parser):
        parser.add_argument("--start", help="First creation date, ISO format.")
        parser.add_argument("--end", help="Last creation date, ISO format.")

    def handle(self, *args, **options):
        yesterday = timezone.now().astimezone(BERLIN).date() - timedelta(days=1)
        try:
            end = date.fromisoformat(options["end"]) if options["end"] else yesterday
            start = date.fromisoformat(options["start"]) if options["start"] else end - timedelta(days=27)
            result = aggregate_bookings(start, end)
        except (ValueError, OverflowError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
