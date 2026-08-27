from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'A+Esthetic Buchung'
admin.site.site_title = 'A+Esthetic Buchung'
admin.site.index_title = 'Verwaltung'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('booking.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
