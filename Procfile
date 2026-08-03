web: cd backend && python manage.py migrate --noinput && python manage.py collectstatic --noinput && python manage.py seed_doctor && gunicorn mays_clinic.wsgi:application --bind 0.0.0.0:$PORT
