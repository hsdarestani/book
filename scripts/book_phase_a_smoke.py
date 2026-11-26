"""Exercise only rollback-scoped synthetic objects on the deployed Django code."""
from datetime import date, timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils.timezone import override

from booking.clinical_time import parse_clinic_wall_time
from booking.models import Appointment, Customer, Service, StaffMember

tag = uuid4().hex
day = date(2026, 12, 30)
with transaction.atomic():
    try:
        admin = get_user_model().objects.create(
            username=f"release-qa-{tag}", is_staff=True, is_superuser=True
        )
        admin.set_unusable_password()
        admin.save(update_fields=["password"])
        patient = Customer.objects.create(first_name="Synthetic", last_name="Release QA",
                                          email=f"{tag}@example.invalid")
        service = Service.objects.create(name=f"Synthetic release {tag}", slug=f"qa-{tag}",
                                         duration_minutes=45, buffer_minutes=10)
        staff = StaffMember.objects.create(display_name=f"Synthetic release {tag}", active=True)
        start = parse_clinic_wall_time(day.isoformat(), "18:30")
        Appointment.objects.create(customer=patient, service=service, staff=staff,
                                   starts_at=start, ends_at=start + timedelta(minutes=55),
                                   treatment_minutes_at_booking=45, status="confirmed")
        client = Client(HTTP_HOST="localhost")
        client.force_login(admin)
        session = client.session
        session["aplus_app_admin"] = True
        session.save()
        for zone in ("Pacific/Honolulu", "Pacific/Kiritimati"):
            with override(zone):
                response = client.get(reverse("booking:admin_calendar_day"),
                                      {"date": day.isoformat(), "staff": staff.pk}, secure=True)
            assert response.status_code == 200
            rows = response.json()["appointments"]
            assert len(rows) == 1
            row = rows[0]
            assert (row["start"], row["treatment_end"], row["end"]) == ("18:30", "19:15", "19:25")
    finally:
        transaction.set_rollback(True)
assert not Customer.objects.filter(email=f"{tag}@example.invalid").exists()
