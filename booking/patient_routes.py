from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

from . import views


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def canonical_patient_file(request, customer_id):
    """Keep legacy patient POST behavior while using one canonical patient UI."""
    if request.method == 'POST':
        return views.patient_file(request, customer_id)

    query = {'customer': customer_id}
    notice = str(request.GET.get('notice') or '').strip()
    if notice:
        query['notice'] = notice
    return redirect(f"/verwaltung/app/patients/?{urlencode(query)}")
