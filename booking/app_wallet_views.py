from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import app_management_views


def _points_redirect(**params):
    clean={key:value for key,value in params.items() if value not in (None,'')}
    suffix=f"?{urlencode(clean)}" if clean else ''
    return redirect(f'/verwaltung/app/wallet/{suffix}')


def _prepare_history(data):
    transactions=[]
    for item in data.get('transactions',[]):
        if str(item.get('kind') or '')!='coin':
            continue
        direction=str(item.get('direction') or ''); sign='+' if direction=='in' else '−'; points=abs(int(item.get('coin_amount') or 0))
        item['display_amount']=f'{sign}{points} Punkte' if points else '—'
        item['created_dt']=parse_datetime(str(item.get('created_at') or ''))
        transactions.append(item)
    data['transactions']=transactions
    customer=data.get('customer') or {}
    customer['points']=int(customer.get('coins') or customer.get('coin_balance') or 0)
    return data


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET','POST'])
def app_wallet_management(request):
    if not request.session.get('aplus_app_admin'):
        return HttpResponseForbidden('A+ App Management ist nur über eine bestätigte A+ Admin-Sitzung verfügbar.')
    try:
        if request.method=='POST':
            action=str(request.POST.get('action') or '').strip()
            if action=='wallet_scan':
                token=str(request.POST.get('qr_token') or '').strip()
                if not token: raise ValueError('Bitte einen QR-Code scannen oder die Karten-ID eingeben.')
                result=app_management_views._api(request,'wallet/lookup/',method='POST',payload={'qr_token':token})
                customer=result.get('customer') or {}; query=str(customer.get('email') or customer.get('member_number') or '').strip(); customer_id=str(customer.get('id') or '').strip()
                if not query: raise ValueError('Die gescannte A+ Karte konnte keinem Patienten zugeordnet werden.')
                return _points_redirect(q=query,wallet=customer_id,scan='1')
            if action=='points_adjust':
                customer_id=int(request.POST.get('customer_id')); delta=int(request.POST.get('point_delta') or 0)
                if not delta: raise ValueError('Bitte eine Punktzahl größer oder kleiner als 0 eingeben.')
                app_management_views._api(request,f'customers/{customer_id}/',method='POST',payload={'coin_delta':delta})
                return _points_redirect(q=request.POST.get('q') or '',wallet=request.POST.get('wallet_id') or customer_id,notice='points')

        query=str(request.GET.get('q') or '').strip(); wallet_id=str(request.GET.get('wallet') or '').strip()
        data=app_management_views._api(request,'customers/',query={'q':query})
        data['customers']=sorted(data.get('customers',[]),key=lambda c: tuple(reversed(str(c.get('name') or '').lower().split(maxsplit=1))))
        for customer in data.get('customers',[]): customer['points']=int(customer.get('coins') or 0)
        history=None
        if wallet_id.isdigit(): history=_prepare_history(app_management_views._api(request,f'customers/{int(wallet_id)}/wallet-history/'))
        return render(request,'booking/app_wallet_management.html',{'section':'wallet','section_title':'A+ Punkte','section_subtitle':'Patient suchen, QR scannen, Punktestand prüfen und manuell anpassen','data':data,'query':query,'wallet_id':wallet_id,'wallet_history':history,'scan_resolved':request.GET.get('scan')=='1','notice':request.GET.get('notice') or ''})
    except PermissionError as exc:
        return render(request,'booking/app_wallet_management.html',{'section':'wallet','section_title':'A+ Punkte','section_subtitle':'Patient suchen, QR scannen und Punkte verwalten','data':{},'query':'','wallet_id':'','wallet_history':None,'error':str(exc),'needs_reauth':True},status=403)
    except (RuntimeError,ValueError,TypeError) as exc:
        return render(request,'booking/app_wallet_management.html',{'section':'wallet','section_title':'A+ Punkte','section_subtitle':'Patient suchen, QR scannen und Punkte verwalten','data':{},'query':str(request.GET.get('q') or '').strip(),'wallet_id':str(request.GET.get('wallet') or '').strip(),'wallet_history':None,'error':str(exc)},status=502)
