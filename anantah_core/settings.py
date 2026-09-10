import os
import sys
from pathlib import Path
from datetime import timedelta
from decouple import config

try:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
except ImportError:
    sentry_sdk = None
    DjangoIntegration = None

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/topics/settings/

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS_CONFIG = config('ALLOWED_HOSTS', default='')
if ALLOWED_HOSTS_CONFIG:
    ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_CONFIG.split(',') if h.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '.onrender.com', '.vercel.app']

# Optional Sentry Monitoring Integration
SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN and sentry_sdk and DjangoIntegration:
    try:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            traces_sample_rate=1.0,
            send_default_pii=False
        )
    except Exception:
        pass

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'cloudinary_storage',
    'django.contrib.staticfiles',
    'cloudinary',
    
    # Third-party apps
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    
    # Custom apps
    'accounts',
    'listings',
    'ai_services',
    'cart',
    'payments',
    'wishlist',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # ADD THIS LINE
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'anantah_core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'anantah_core.wsgi.application'

# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

import socket

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT', cast=int),
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
            'ssl': {'ca': str(BASE_DIR / 'certs' / 'aiven-ca.pem')},
        }
    }
}

# Check if MySQL host is reachable
mysql_reachable = False
if 'test' not in sys.argv:
    try:
        host = config('DB_HOST')
        port = config('DB_PORT', cast=int)
        socket.gethostbyname(host)
        # Try a quick socket connection (timeout 5s) to make sure database is online
        with socket.create_connection((host, port), timeout=5.0):
            mysql_reachable = True
    except Exception:
        mysql_reachable = False

if 'test' in sys.argv or not mysql_reachable:
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files setup (for raw and refined artisan images)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Cloudinary Centralized Media Storage Configuration
CLOUDINARY_CLOUD_NAME = config('CLOUDINARY_CLOUD_NAME', default='')
CLOUDINARY_API_KEY = config('CLOUDINARY_API_KEY', default='')
CLOUDINARY_API_SECRET = config('CLOUDINARY_API_SECRET', default='')

CLOUDINARY_CONFIGURED = bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)

if CLOUDINARY_CONFIGURED:
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': CLOUDINARY_CLOUD_NAME,
        'API_KEY': CLOUDINARY_API_KEY,
        'API_SECRET': CLOUDINARY_API_SECRET,
    }

# Django 5 Storages configuration
if CLOUDINARY_CONFIGURED and 'test' not in sys.argv:
    STORAGES = {
        "default": {
            "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
        },
        "staticfiles": {
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
},
        "audio": {
            "BACKEND": "cloudinary_storage.storage.VideoMediaCloudinaryStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
},
        "audio": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
    }
# DEFAULT_FILE_STORAGE is handled by STORAGES in Django 4.2+ / 5.x


# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
        'payments_create': '10/minute',
        'payments_verify': '10/minute',
        'otp_request': '15/hour',
        'otp_verify': '5/minute',
        'product_upload': '20/minute',
        'voice_catalog': '20/minute',
        'product_view': '60/minute',
    }
}

# JWT SimpleJWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# CORS Configuration
CORS_ALLOWED_ORIGINS_CONFIG = config('CORS_ALLOWED_ORIGINS', default='')
if CORS_ALLOWED_ORIGINS_CONFIG:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in CORS_ALLOWED_ORIGINS_CONFIG.split(',') if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False
elif DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'https://anantah.vercel.app',
    ]

if not DEBUG:
    # Django Security Headers (Production)
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Django Caching Framework (for temporary OTP verification status)
REDIS_URL = config('REDIS_URL', default=None)
if REDIS_URL and 'test' not in sys.argv:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'anantah-otp-cache',
        }
    }

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Razorpay Configuration
RAZORPAY_KEY_ID = config('RAZORPAY_KEY_ID', default='')
RAZORPAY_KEY_SECRET = config('RAZORPAY_KEY_SECRET', default='')
RAZORPAY_WEBHOOK_SECRET = config('RAZORPAY_WEBHOOK_SECRET', default='')
