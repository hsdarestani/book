from django.core.management.base import BaseCommand

from booking.customer_identity import duplicate_customer_groups, merge_customer
from booking.models import Customer


class Command(BaseCommand):
    help = "Report duplicate customers. Merging is opt-in with --apply and is never run by SimplyBook sync."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually merge exact duplicate groups. Without this flag no data is changed.",
        )

    def handle(self, *args, **options):
        groups = [
            group
            for group in duplicate_customer_groups(Customer.objects.order_by("pk"))
            if len(group) > 1
        ]
        duplicate_rows = sum(len(group) - 1 for group in groups)

        if not options.get("apply"):
            self.stdout.write(self.style.WARNING(
                f"Duplicate report only: groups={len(groups)}, duplicate_rows={duplicate_rows}, changed=0"
            ))
            return

        merged = 0
        for group in groups:
            existing = [item for item in group if Customer.objects.filter(pk=item.pk).exists()]
            if len(existing) < 2:
                continue
            keeper = sorted(existing, key=lambda item: item.pk)[0]
            for duplicate in sorted(existing, key=lambda item: item.pk)[1:]:
                if Customer.objects.filter(pk=duplicate.pk).exists():
                    keeper = merge_customer(keeper, duplicate)
                    merged += 1

        self.stdout.write(self.style.SUCCESS(
            f"Explicit customer merge completed: groups={len(groups)}, merged={merged}"
        ))
