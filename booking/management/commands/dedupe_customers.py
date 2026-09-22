from collections import defaultdict

from django.core.management.base import BaseCommand

from booking.customer_identity import merge_customer, normalize_email, normalize_name, normalize_phone
from booking.models import Customer


class Command(BaseCommand):
    help = "Safely merge duplicate customers while preserving appointments and patient records."

    def handle(self, *args, **options):
        merged = 0
        by_email = defaultdict(list)
        for customer in Customer.objects.order_by("pk"):
            key = normalize_email(customer.email)
            if key:
                by_email[key].append(customer)

        for group in by_email.values():
            if len(group) < 2:
                continue
            keeper = group[0]
            for duplicate in group[1:]:
                if Customer.objects.filter(pk=duplicate.pk).exists():
                    keeper = merge_customer(keeper, duplicate)
                    merged += 1

        by_identity = defaultdict(list)
        for customer in Customer.objects.order_by("pk"):
            phone = normalize_phone(customer.phone)
            first = normalize_name(customer.first_name)
            last = normalize_name(customer.last_name)
            if phone and first and last:
                by_identity[(phone, first, last)].append(customer)

        for group in by_identity.values():
            if len(group) < 2:
                continue
            group = sorted(group, key=lambda item: (0 if normalize_email(item.email) else 1, item.pk))
            keeper = group[0]
            for duplicate in group[1:]:
                if Customer.objects.filter(pk=duplicate.pk).exists():
                    keeper = merge_customer(keeper, duplicate)
                    merged += 1

        self.stdout.write(self.style.SUCCESS(f"Customer de-duplication completed: merged={merged}"))
