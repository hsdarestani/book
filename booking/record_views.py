from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Customer
from .record_previews import fallback_preview, file_kind, pdf_page_count, preview_bytes, text_excerpt
from .views import _doctor_patient_scope, _doctor_visible_records, _patient_file_path


def _authorized_record(request, customer_id, record_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    staff = _doctor_patient_scope(request, customer)
    record = get_object_or_404(_doctor_visible_records(request, customer, staff), public_id=record_id)
    return customer, record


def _page_number(value):
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


@staff_member_required(login_url='/verwaltung/login/')
@never_cache
@require_GET
def record_view(request, customer_id, record_id):
    customer, record = _authorized_record(request, customer_id, record_id)
    path = _patient_file_path(record.stored_name) if record.stored_name else None
    kind = file_kind(record)
    available = bool(path and path.is_file())
    error = ''
    pages = 1
    excerpt = ''
    if not available:
        error = 'Die Datei ist derzeit nicht verfügbar.'
    else:
        try:
            if kind == 'pdf':
                pages = pdf_page_count(path)
                if not pages:
                    raise ValueError('Empty PDF')
            elif kind == 'image':
                preview_bytes(path, kind)
            elif kind == 'text':
                excerpt = text_excerpt(path)
        except Exception:
            error = 'Für diese Datei konnte keine Vorschau erstellt werden. Die Originaldatei kann heruntergeladen werden.'
    page = min(_page_number(request.GET.get('page')), max(pages, 1))
    kwargs = {'customer_id': customer_id, 'record_id': record_id}
    from .doctor_views import _doctor_staff
    back_url = (reverse('booking:patient_file', kwargs={'customer_id': customer_id})
                if _doctor_staff(request) else
                reverse('booking:app_management', kwargs={'section': 'patients'}) + f'?customer={customer_id}&tab=records')
    return render(request, 'booking/record_view.html', {
        'record': record, 'kind': kind, 'available': available, 'preview_error': error,
        'page_number': page, 'page_count': pages, 'previous_page': page - 1 if page > 1 else None,
        'next_page': page + 1 if page < pages else None, 'text_preview': excerpt,
        'file_url': reverse('booking:patient_record_file', kwargs=kwargs),
        'preview_url': reverse('booking:patient_record_preview', kwargs=kwargs),
        'back_url': back_url,
    })


@staff_member_required(login_url='/verwaltung/login/')
@never_cache
@require_GET
def record_preview(request, customer_id, record_id):
    _, record = _authorized_record(request, customer_id, record_id)
    path = _patient_file_path(record.stored_name) if record.stored_name else None
    try:
        if not path or not path.is_file():
            raise ValueError('Missing file')
        data = preview_bytes(path, file_kind(record), page=_page_number(request.GET.get('page')),
                             full=request.GET.get('size') == 'page')
        state = 'ready'
    except Exception:
        data = fallback_preview()
        state = 'unavailable'
    response = HttpResponse(data, content_type='image/jpeg')
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    response['X-Preview-State'] = state
    return response
