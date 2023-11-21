from channels.routing import ProtocolTypeRouter
from django.core.asgi import get_asgi_application
from channels.routing import URLRouter
import todo.routing

django_asgi_app = get_asgi_application()
application = ProtocolTypeRouter({
    'http': django_asgi_app,
    # Empty for now (http->django views is added by default)
    'websocket': URLRouter(todo.routing.websocket_urlpatterns),
})