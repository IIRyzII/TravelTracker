"""Production entry point:  gunicorn wsgi:app"""

from orbit import create_app

app = create_app()
