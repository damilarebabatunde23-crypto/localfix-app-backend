import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'localfix_mobile_api.settings')
application = get_wsgi_application()

# Ensure database tables exist automatically on Render container boot
try:
    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)
except Exception as exc:
    print(f'Startup auto-migrate warning: {exc}')

# Optional env-driven admin superuser bootstrap (set DJANGO_SUPERUSER_USERNAME & DJANGO_SUPERUSER_PASSWORD on Render)
try:
    su_user = os.environ.get('DJANGO_SUPERUSER_USERNAME', '').strip()
    su_pass = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '').strip()
    su_email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@localfix.app').strip()
    if su_user and su_pass:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=su_user,
            defaults={'email': su_email, 'is_staff': True, 'is_superuser': True},
        )
        if created or not user.is_superuser or not user.is_staff or not user.check_password(su_pass):
            user.email = su_email
            user.is_staff = True
            user.is_superuser = True
            user.set_password(su_pass)
            user.save()
except Exception as exc:
    print(f'Startup superuser bootstrap warning: {exc}')
