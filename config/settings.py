import base64
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-change-me')
DEBUG = os.getenv('DJANGO_DEBUG', '0') == '1'
ALLOWED_HOSTS = [x.strip() for x in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if x.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if x.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'booking',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]
WSGI_APPLICATION = 'config.wsgi.application'

if os.getenv('DB_ENGINE') == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'aestheticbook'),
            'USER': os.getenv('DB_USER', 'aestheticbook'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', ''),
            'PORT': os.getenv('DB_PORT', ''),
            'CONN_MAX_AGE': 60,
        }
    }
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'de-de'
TIME_ZONE = 'Europe/Berlin'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Patient files intentionally live outside MEDIA_ROOT. They are never served by
# Caddy/Nginx directly; authenticated staff views stream them after permission checks.
PATIENT_FILES_ROOT = Path(os.getenv('PATIENT_FILES_ROOT', str(BASE_DIR / 'private_patient_files')))
PATIENT_FILE_MAX_BYTES = int(os.getenv('PATIENT_FILE_MAX_BYTES', str(25 * 1024 * 1024)))
PATIENT_FILE_ALLOWED_EXTENSIONS = {
    '.pdf', '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif',
    '.doc', '.docx', '.xls', '.xlsx', '.txt', '.rtf', '.csv',
}
# Optional shared-token auth plus a fail-closed DNS/IP allowlist for trusted
# A+Esthetic server-to-server synchronization. Neither path is exposed to clients.
PATIENT_SYNC_TOKEN = os.getenv('PATIENT_SYNC_TOKEN', '')
PATIENT_SYNC_TOKEN_FILE = os.getenv('PATIENT_SYNC_TOKEN_FILE', '/etc/aesthetic-patient-sync.token')
PATIENT_SYNC_ALLOWED_HOSTS = [
    x.strip() for x in os.getenv('PATIENT_SYNC_ALLOWED_HOSTS', 'esthetic.smarbiz.sbs').split(',') if x.strip()
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/admin/login/'
LOGIN_REDIRECT_URL = '/verwaltung/'

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

AESTHETIC_MEMBER_API_URL = os.getenv(
    'AESTHETIC_MEMBER_API_URL',
    'https://esthetic.smarbiz.sbs/api/mobile/me/',
)
BOOKING_NOTIFICATION_EMAIL = os.getenv('BOOKING_NOTIFICATION_EMAIL', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'A+Esthetic <termin@a-esthetic.de>')
if os.getenv('EMAIL_HOST'):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = os.getenv('EMAIL_HOST')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', '465'))
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
    encoded_password = os.getenv('EMAIL_HOST_PASSWORD_B64', '')
    EMAIL_HOST_PASSWORD = (
        base64.b64decode(encoded_password.encode('ascii')).decode('utf-8')
        if encoded_password
        else os.getenv('EMAIL_HOST_PASSWORD', '')
    )
    EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', '1') == '1'
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', '0') == '1'
    EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '15'))
    if EMAIL_USE_SSL and EMAIL_USE_TLS:
        raise ValueError('EMAIL_USE_SSL und EMAIL_USE_TLS dürfen nicht gleichzeitig aktiviert sein.')
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
