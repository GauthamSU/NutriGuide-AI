"""
Django settings for config project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-540c^-)ohegx$ih&w2d)+-f*ukt*f59*!o%w1i4p+f7t1h3-nv'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'nutrition',
    'chat_history.apps.ChatHistoryConfig',
]

MIDDLEWARE = [
    'config.cors.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'CORS_ALLOWED_ORIGINS',
        'http://127.0.0.1:5500,http://localhost:5500',
    ).split(',')
    if origin.strip()
]

ROOT_URLCONF = 'config.urls'

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

WSGI_APPLICATION = 'config.wsgi.application'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.server': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'nutrition': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


# Database
# 'default' / 'core_app' (core_app.sqlite3) is the primary application database storing
# all application tables: auth, sessions, admin, contenttypes, user profiles, nutrition groups,
# tracker, chat history, meal plans, and all future tables.
# 'nutrition' (db.sqlite3) is strictly a read-only cache database containing ONLY IFCT 2017
# reference data inside the container.

CORE_APP_DB_ENGINE = os.getenv(
    'CORE_APP_DB_ENGINE',
    os.getenv('CHAT_HISTORY_DB_ENGINE', 'django.db.backends.sqlite3'),
)
CORE_APP_DB_NAME = os.getenv(
    'CORE_APP_DB_NAME',
    os.getenv('CHAT_HISTORY_DB_NAME', str(BASE_DIR / 'core_app.sqlite3')),
)
if (
    CORE_APP_DB_ENGINE == 'django.db.backends.sqlite3'
    and not Path(CORE_APP_DB_NAME).is_absolute()
):
    CORE_APP_DB_NAME = str(BASE_DIR / CORE_APP_DB_NAME)

NUTRITION_DB_ENGINE = os.getenv(
    'NUTRITION_DB_ENGINE', 'django.db.backends.sqlite3'
)
NUTRITION_DB_NAME = os.getenv(
    'NUTRITION_DB_NAME', str(BASE_DIR / 'db.sqlite3')
)
if (
    NUTRITION_DB_ENGINE == 'django.db.backends.sqlite3'
    and not Path(NUTRITION_DB_NAME).is_absolute()
):
    NUTRITION_DB_NAME = str(BASE_DIR / NUTRITION_DB_NAME)

CORE_APP_CONFIG = {
    'ENGINE': CORE_APP_DB_ENGINE,
    'NAME': CORE_APP_DB_NAME,
    'USER': os.getenv('CORE_APP_DB_USER', os.getenv('CHAT_HISTORY_DB_USER', '')),
    'PASSWORD': os.getenv('CORE_APP_DB_PASSWORD', os.getenv('CHAT_HISTORY_DB_PASSWORD', '')),
    'HOST': os.getenv('CORE_APP_DB_HOST', os.getenv('CHAT_HISTORY_DB_HOST', '')),
    'PORT': os.getenv('CORE_APP_DB_PORT', os.getenv('CHAT_HISTORY_DB_PORT', '')),
}

DATABASES = {
    'default': {
        'ENGINE': CORE_APP_DB_ENGINE,
        'NAME': CORE_APP_DB_NAME,
        'USER': os.getenv('CORE_APP_DB_USER', os.getenv('CHAT_HISTORY_DB_USER', '')),
        'PASSWORD': os.getenv('CORE_APP_DB_PASSWORD', os.getenv('CHAT_HISTORY_DB_PASSWORD', '')),
        'HOST': os.getenv('CORE_APP_DB_HOST', os.getenv('CHAT_HISTORY_DB_HOST', '')),
        'PORT': os.getenv('CORE_APP_DB_PORT', os.getenv('CHAT_HISTORY_DB_PORT', '')),
    },
    'nutrition': {
        'ENGINE': NUTRITION_DB_ENGINE,
        'NAME': NUTRITION_DB_NAME,
    },
}
DATABASE_ROUTERS = ['chat_history.db_router.CoreAppDatabaseRouter']
MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
MEDIA_ROOT = Path(
    os.getenv(
        'CORE_APP_MEDIA_ROOT',
        os.getenv('CHAT_HISTORY_MEDIA_ROOT', str(BASE_DIR / 'media')),
    )
)


# Password validation

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

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = 'static/'


# Email

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

# ─── Inference Backend Switch ───────────────────────────────────────────────
# Options: 'local' (llama-cpp server) or 'gemini' (Google Gemini API)
INFERENCE_BACKEND = os.getenv('INFERENCE_BACKEND', 'local').strip().lower()

# ─── Local Gemma 4 / llama.cpp Server Settings ─────────────────────────────
LLAMA_SERVER_HOST = os.getenv('LLAMA_SERVER_HOST', '127.0.0.1')
LLAMA_SERVER_PORT = int(os.getenv('LLAMA_SERVER_PORT', '8080'))
LLAMA_SERVER_BASE_URL = os.getenv(
    'LLAMA_SERVER_BASE_URL',
    f'http://{LLAMA_SERVER_HOST}:{LLAMA_SERVER_PORT}/v1',
)
LLAMA_CPP_DIR = Path(os.getenv('LLAMA_CPP_DIR', r'D:\llama-cpp'))
LLAMA_MODEL_PATH = Path(
    os.getenv('LLAMA_MODEL_PATH', r'D:\models\gemma-4-E2B-it-Q4_K_M.gguf')
)
LLAMA_MMPROJ_PATH = Path(
    os.getenv('LLAMA_MMPROJ_PATH', r'D:\models\mmproj-F16.gguf')
)
LLAMA_MODEL_NAME = os.getenv('LLAMA_MODEL_NAME', 'gemma-4-E2B-it-Q4_K_M.gguf')
LLAMA_TIMEOUT_SECONDS = float(os.getenv('LLAMA_TIMEOUT_SECONDS', '120'))

# ─── Google Gemini API Settings ─────────────────────────────────────────────
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL_NAME', 'gemini-3.6-flash')
GEMINI_BASE_URL = os.getenv(
    'GEMINI_BASE_URL',
    'https://generativelanguage.googleapis.com/v1beta/openai/',
)
GEMINI_TIMEOUT_SECONDS = float(os.getenv('GEMINI_TIMEOUT_SECONDS', '60'))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv('LLM_MAX_OUTPUT_TOKENS', '1800'))
LLM_RESPONSE_DEBUG_FILE = Path(
    os.getenv('LLM_RESPONSE_DEBUG_FILE', str(BASE_DIR / 'llm_response_debug.json'))
)
API_RESPONSE_DEBUG_FILE = Path(
    os.getenv('API_RESPONSE_DEBUG_FILE', str(BASE_DIR / 'api_response_debug.json'))
)
