from workers import asgi

from champbot.main import app

Default = asgi.entrypoint(app)
