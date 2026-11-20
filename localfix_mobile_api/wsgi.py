import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localfix_mobile_api.settings')
application = get_wsgi_application()

# Ensure SQLite tables exist automatically on Render ephemeral container boot
try:
    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)
except Exception as exc:
    print(f'Startup auto-migrate warning: {exc}')
