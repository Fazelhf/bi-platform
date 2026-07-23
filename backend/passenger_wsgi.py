"""
Entry point for cPanel / LiteSpeed "Setup Python App" (Passenger).

Point the Python App's *Application startup file* at this file and its
*Application Entry point* at `application`. Passenger imports this module and
serves the `application` callable.
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402  (must follow env setup)
