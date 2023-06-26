from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, RedirectResponse


class OAuthMiddleware(BaseHTTPMiddleware):
    """Gate all routes behind OAuth."""

    def __init__(self, app, oauth, permissions={}):
        super().__init__(app)
        self.oauth = oauth
        self.router = app
        self.permissions = permissions
        while not hasattr(self.router, "add_route"):
            self.router = self.router.app
        self.add_routes()

    def is_authorized(self, user, path):
        parts = path.split("/")
        email = user["email"]
        for i in range(len(parts)):
            if email in self.permissions.get("/".join(parts[: i + 1]) or "/", []):
                return True
        return False

    def add_routes(self):
        self.router.add_route("/_/login", self.route_login)
        self.router.add_route("/_/logout", self.route_logout)
        self.router.add_route("/_/auth", self.route_auth, name="auth")

    async def route_login(self, request):
        redirect_uri = request.url_for("auth")
        return await self.oauth.google.authorize_redirect(request, str(redirect_uri))

    async def route_auth(self, request):
        token = await self.oauth.google.authorize_access_token(request)
        user = token.get("userinfo")
        if user:
            request.session["user"] = user
        red = request.session.get("redirect_after_login", "/")
        return RedirectResponse(url=red)

    async def route_logout(self, request):
        request.session.pop("user", None)
        return RedirectResponse(url="/")

    async def dispatch(self, request, call_next):
        if (path := request.url.path).startswith("/_/"):
            return await call_next(request)

        user = request.session.get("user")
        if not user:
            request.session["redirect_after_login"] = str(request.url)
            return RedirectResponse(url="/_/login")
        elif not self.is_authorized(user, path):
            return PlainTextResponse("Forbidden", status_code=403)
        else:
            return await call_next(request)
