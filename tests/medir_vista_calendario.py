import os
import sys
import time

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from django.db import connection, reset_queries
from django.test import Client
from django.conf import settings
from agenda.models import Sesion

settings.DEBUG = True

user = User.objects.get(username='test_perf')
client = Client()
client.force_login(user)

total_sesiones_bd = Sesion.objects.count()
print(f"Total de sesiones en la BD: {total_sesiones_bd}")

reset_queries()
t0 = time.perf_counter()
resp = client.get('/agenda/', {'vista': 'lista', 'por_pagina': '25'})
elapsed = time.perf_counter() - t0
n_queries = len(connection.queries)

print(f"status_code = {resp.status_code}")
print(f"queries SQL para renderizar página 1 (25 filas): {n_queries}")
print(f"tiempo de la vista: {elapsed*1000:.1f} ms")
