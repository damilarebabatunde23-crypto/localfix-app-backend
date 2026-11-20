# LocalFix Mobile Django Backend

Dedicated **Django 5 + Django REST Framework** backend inside `mobile/backend/` powering the LocalFix Flutter mobile app, matching the main LocalFix web backend stack.

## Quick Start
```bash
cd mobile/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations mobile_api
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

## API Endpoints
- `GET /api/health/` — Server health check
- `POST /api/auth/login/` & `POST /api/auth/register/` — Authentication
- `GET / PUT / PATCH /api/profile/` — Full editable user profile
- `GET / POST /api/feed/` — Home feed posts
- `GET / POST /api/reels/` — Watch page reels & video publishing
- `GET /api/artisans/nearby/?radiusKm=15` — Worldwide GPS artisan search
- `GET /api/escrow/` — Escrow vault balance & contract custody status
- `GET /admin/` — Django Admin panel
