from django.urls import path
from . import views

app_name = 'profesionales'

urlpatterns = [
    path('', views.lista_profesionales, name='lista'),
    path('<int:pk>/', views.detalle_profesional, name='detalle'),
]