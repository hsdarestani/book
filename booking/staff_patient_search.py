"""Search the full authorized Book patient catalog without returning medical data."""
import json

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F, Q, Value
from django.db.models.functions import Replace
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .doctor_views import _doctor_staff, _own_customer_ids
from .models import Customer


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_POST
def staff_patient_search(request):
    profile = getattr(request.user, 'aesthetic_access', None)
    patients = Customer.objects.all()
    if profile and profile.view_only:
        staff = _doctor_staff(request)
        if not staff:
            return JsonResponse({'ok': False}, status=403)
        patients = patients.filter(pk__in=_own_customer_ids(staff))
    try:
        data = json.loads(request.body) if len(request.body) <= 1024 else None
    except (UnicodeError, ValueError):
        data = None
    query = data.get('query') if isinstance(data, dict) else None
    offset = data.get('offset', 0) if isinstance(data, dict) else None
    if (not isinstance(query, str) or not query.isprintable() or not 2 <= len(query.strip()) <= 80
            or type(offset) is not int or not 0 <= offset <= 100000):
        return JsonResponse({'ok': False}, status=400)
    digits = ''.join(c for c in query if c in '0123456789')
    if len(digits) >= 2 and all(c in '+0123456789 .()-/' for c in query):
        phone = F('phone')
        for char in '+ .()-/':
            phone = Replace(phone, Value(char), Value(''))
        patients = patients.annotate(phone_digits=phone).filter(phone_digits__contains=digits)
    else:
        for term in query.split():
            patients = patients.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term)
                                       | Q(email__icontains=term) | Q(phone__icontains=term))
    rows = list(patients.only('first_name', 'last_name', 'email', 'phone', 'date_of_birth')
                .order_by('last_name', 'first_name', 'pk')[offset:offset + 26])
    return JsonResponse({'ok': True, 'patients': [
        {'id': row.pk, 'name': row.full_name, 'email': row.email, 'phone': row.phone,
         'birth_date': row.date_of_birth.strftime('%d.%m.%Y') if row.date_of_birth else ''}
        for row in rows[:25]
    ], 'next_offset': offset + 25 if len(rows) > 25 else None},
        headers={'Cache-Control': 'private, no-store, max-age=0'})
