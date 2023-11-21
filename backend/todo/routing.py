# routing.py

from django.urls import path
from .consumers import YourConsumer

websocket_urlpatterns = [
    path('ws/test/', YourConsumer.as_asgi()),
]