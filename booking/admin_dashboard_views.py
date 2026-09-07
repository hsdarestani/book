from urllib.parse import quote

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import app_management_views
from .models import Appointment, Customer, WhatsAppTemplate


def _is_view_only(user):
    profile = getattr(user, 'aesthetic_access', None)
    return bool(profile and profile.view_only)


def _wa_phone(value):
    raw = ''.join(ch for ch in str(value or '') if ch.isdigit() or ch == '+')
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = '49' + digits[1:]
    return digits


def _customer_actions(customer):
    phone = _wa_phone(customer.phone)
    templates = []
    if phone:
        for item in WhatsAppTemplate.objects.filter(active=True):
            text = item.render_for(customer)
            templates.append({
                'id': item.pk,
                'name': item.name,
                'text': text,
                'url': f'https://wa.me/{phone}?text={quote(text)}',
            })
    return {
        'call_url': f'tel:{customer.phone}' if customer.phone else '',
        'whatsapp_url': f'https://wa.me/{phone}' if phone else '',
        'templates': templates,
    }


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def admin_dashboard(request):
    view_only = _is_view_only(request.user)
    if request.method == 'POST':
        if view_only:
            return HttpResponseForbidden('Dieser Zugang ist nur zum Ansehen freigeschaltet.')
        action = str(request.POST.get('action') or '').strip()
        try:
            if action == 'template_save':
                template_id = str(request.POST.get('template_id') or '').strip()
                item = WhatsAppTemplate.objects.filter(pk=int(template_id)).first() if template_id.isdigit() else None
                name = str(request.POST.get('name') or '').strip()
                body = str(request.POST.get('body') or '').strip()
                if not name or not body:
                    raise ValueError('Name und Text der Vorlage sind erforderlich.')
                if not item:
                    item = WhatsAppTemplate()
                item.name = name[:100]
                item.body = body[:5000]
                item.active = request.POST.get('active') == 'on'
                item.sort_order = max(0, min(9999, int(request.POST.get('sort_order') or 100)))
                item.save()
                return redirect('/verwaltung/dashboard/?saved=template#whatsapp-templates')

            if action == 'template_delete':
                template_id = int(request.POST.get('template_id'))
                WhatsAppTemplate.objects.filter(pk=template_id).delete()
                return redirect('/verwaltung/dashboard/?saved=template#whatsapp-templates')

            if action in {'banner_save', 'banner_delete'}:
                payload = {'action': 'delete' if action == 'banner_delete' else 'save'}
                banner_id = str(request.POST.get('banner_id') or '').strip()
                if banner_id.isdigit():
                    payload['id'] = int(banner_id)
                if action == 'banner_save':
                    payload.update({
                        'title': request.POST.get('title') or '',
                        'text': request.POST.get('text') or '',
                        'image_url': request.POST.get('image_url') or '',
                        'cta_label': request.POST.get('cta_label') or '',
                        'cta_url': request.POST.get('cta_url') or '',
                        'active': request.POST.get('active') == 'on',
                        'starts_at': request.POST.get('starts_at') or '',
                        'ends_at': request.POST.get('ends_at') or '',
                        'sort_order': int(request.POST.get('sort_order') or 100),
                    })
                app_management_views._api(request, 'dashboard-banners/', method='POST', payload=payload)
                return redirect('/verwaltung/dashboard/?saved=banner#campaigns')
        except (PermissionError, RuntimeError, ValueError, TypeError) as exc:
            error = str(exc)
        else:
            error = ''
    else:
        error = ''

    query = str(request.GET.get('q') or '').strip()
    customers = Customer.objects.all().order_by('last_name', 'first_name')
    if query:
        customers = customers.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
        )
    customers = list(customers[:80 if query else 12])

    now = timezone.now()
    next_appointment = Appointment.objects.select_related('customer', 'service', 'staff').filter(
        starts_at__gte=now,
    ).exclude(status='cancelled').order_by('starts_at').first()
    next_day = timezone.localtime(next_appointment.starts_at).date() if next_appointment else None
    next_day_appointments = []
    if next_day:
        next_day_appointments = list(
            Appointment.objects.select_related('customer', 'service', 'staff')
            .filter(starts_at__date=next_day)
            .exclude(status='cancelled')
            .order_by('starts_at', 'customer__last_name', 'customer__first_name')
        )

    banners = []
    banners_error = ''
    if request.session.get('aplus_app_admin'):
        try:
            banners = app_management_views._api(request, 'dashboard-banners/').get('banners', [])
        except (PermissionError, RuntimeError) as exc:
            banners_error = str(exc)

    return render(request, 'booking/admin_dashboard_lambo.html', {
        'query': query,
        'customers': customers,
        'customer_actions': {customer.pk: _customer_actions(customer) for customer in customers},
        'next_day': next_day,
        'next_day_appointments': next_day_appointments,
        'today_count': Appointment.objects.filter(starts_at__date=timezone.localdate()).exclude(status='cancelled').count(),
        'upcoming_count': Appointment.objects.filter(starts_at__gte=now).exclude(status='cancelled').count(),
        'patient_count': Customer.objects.count(),
        'banners': banners,
        'banners_error': banners_error,
        'templates': WhatsAppTemplate.objects.all(),
        'view_only': view_only,
        'error': error,
        'saved': request.GET.get('saved') or '',
    })
