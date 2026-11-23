"""Read-only Chromium regression for screenshot-guided MediLogin GOÄ user flow.
Isolated Django template rendered with synthetic data; NEVER posts or prints real patient data.
"""
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()

from django.template.loader import get_template
from playwright.sync_api import sync_playwright
template=get_template('booking/_billing_goae_form.html')
html='<html lang="de"><head><meta charset="utf-8"></head><body>'+template.render({
 'csrf_token':'browser-test-only',
 'data':{'customers':[{'id':1,'name':'Anna Muster','email':'synthetic@example.test'}],
    'settings':{'company_name':'Privatpraxis Test', 'street':'Musterstr. 1',
      'postal_code':'60313','city':'Frankfurt','tax_number':'000/000/000'}},
 'goae_catalog':[
   {'number':'1','de':'Beratung, auch telefonisch','points':80,'category':'general'},
   {'number':'5','de':'Symptombezogene Untersuchung','points':80,'category':'general'},
   {'number':'2442','de':'Implantation alloplastischen Materials zur Weichteilunterfütterung','points':900,'category':'general'},
 ],
 'goae_treatments':{'hyaluron':['2442','1','5'],'botox':['1','5'],'prp':['1','5'],'lipolysis':['1','5']}
})+'</body></html>'

def smoke():
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  page=browser.new_page(locale='en-US',viewport={'width':1280,'height':900})
  errors=[]; requests=[]
  page.on('pageerror',lambda error: errors.append(str(error)))
  base='https://aesthetic-synthetic.test'
  css=(ROOT/'static/booking/goae-rechner-v2.css').read_text(encoding='utf-8')
  js=(ROOT/'static/booking/goae-rechner-v2.js').read_text(encoding='utf-8')
  page.route(base+'/',lambda route: route.fulfill(status=200,content_type='text/html',body=html))
  page.route(base+'/static/booking/goae-rechner-v2.css*',lambda route: route.fulfill(status=200,content_type='text/css',body=css))
  page.route(base+'/static/booking/goae-rechner-v2.js*',lambda route: route.fulfill(status=200,content_type='application/javascript',body=js))
  page.route('**/verwaltung/api/goae-quote/',lambda route: requests.append(route.request.post_data) or route.fulfill(
    status=400,content_type='application/json',body='{"ok":false,"message":"Synthetic quote rejected: no clinical confirmation."}'))
  page.goto(base+'/',wait_until='networkidle')
  page.locator('[data-total]').wait_for(state='visible')
  assert page.locator('[data-total]').inner_text()=='260,00 €' or page.locator('[data-total]').inner_text()=='260,00 €'
  assert '142,06' in page.locator('[data-fee]').inner_text(),page.locator('[data-fee]').inner_text()
  assert '76,43' in page.locator('[data-material-total]').inner_text()
  assert '41,51' in page.locator('[data-tax]').inner_text()
  assert page.locator('.mlr-summary .mlr-status-warning').count()==1
  assert page.locator('#goaeDetails').get_attribute('open') is None
  page.locator('[data-qty-plus]').click()
  assert '2' in page.locator('[data-qty]').inner_text()
  assert '152,86' in page.locator('[data-material-total]').inner_text()
  page.locator('[data-qty-minus]').click()
  page.locator('[data-preset="400"]').click()
  assert '400,00' in page.locator('[data-total]').inner_text()
  page.locator('[data-treatment="botox"]').click()
  assert page.locator('[data-treatment="botox"]').get_attribute('aria-pressed')=='true'
  page.locator('[data-treatment="hyaluron"]').click()
  page.locator('#goaeDetails>summary').click()
  assert page.locator('#goaeDetails').get_attribute('open') is not None
  assert page.locator('.mlr-line').count()==3
  date=page.locator('#goaeDateGerman')
  assert date.get_attribute('placeholder')=='TT.MM.JJJJ'
  date.fill('23.11.2026')
  assert page.locator('#goaeDateIso').input_value()==''
  # No clinical identity selected: client must NOT post.
  page.locator('[data-goae-preview]').click()
  assert len(requests)==0
  assert 'Patient auswählen' in page.locator('[data-goae-feedback]').inner_text()
  page.locator('#goaePatient').select_option('1')
  page.locator('[data-goae-preview]').click()
  assert len(requests)==0, 'Server must not quote clinically unconfirmed GOÄ positions'
  assert 'behandelnden' in page.locator('[data-goae-feedback]').inner_text()
  for checkbox in page.locator('[data-g="clinical_confirmed"]').all():
    checkbox.check()
  page.locator('[data-goae-preview]').click()
  assert len(requests)==1
  assert 'Synthetic quote rejected' in page.locator('[data-goae-feedback]').inner_text()
  assert page.locator('#goaeDateIso').input_value()=='2026-11-23'
  page.set_viewport_size({'width':390,'height':840})
  page.wait_for_timeout(160)
  sizes=page.evaluate('''() => ({body:document.body.scrollWidth,view:document.documentElement.clientWidth})''')
  assert sizes['body']<=sizes['view']+4, 'Mobile horizontal overflow '+str(sizes)
  assert not errors,'Unexpected browser errors: '+str(errors)
  page.screenshot(path='/tmp/goae-mobile-390.png',full_page=True)
  print('PASS: reference UI, 260=>142.06+76.43+41.51, 4 treatment choices, quantity, slider presets, details, German date, no patient/no POST guard, mobile 390px; no real invoices created')
  browser.close()

if __name__=='__main__':
 smoke()
