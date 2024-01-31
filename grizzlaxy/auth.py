from collections import defaultdict
from fnmatch import fnmatch

from hrepr import H
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, RedirectResponse

from .utils import make_config


class PermissionDict:
    def __init__(self, permissions):
        self.permissions = permissions
        self.reset()

    def reset(self):
        self.cache = defaultdict(dict)
        self.wild = defaultdict(list)
        for path, allowed in self.permissions.items():
            if path == "/":
                path = ("",)
            else:
                path = tuple(path.split("/"))
            for user in allowed:
                if "*" in user:
                    self.wild[path].append(user)
                else:
                    self.cache[path][user] = True

    def __call__(self, user, path):
        path, *_ = path.split("!", 1)
        path = path.removesuffix("/")
        if path == "/":
            parts = ("",)
        else:
            parts = tuple(path.split("/"))
        email = user["email"]
        partials = [(*parts[: i + 1], "**") for i in range(len(parts))]
        to_check = [parts, *partials]
        for current in to_check:
            cache = self.cache[current]
            if email in cache:
                if cache[email]:
                    return True
            else:
                for wild in self.wild[current]:
                    if fnmatch(email, wild):
                        cache[email] = True
                        return True
                else:
                    cache[email] = False
        return False


class PermissionFile(PermissionDict):
    def __init__(self, permissions_file, defaults=None):
        self.file = make_config(permissions_file, defaults=defaults)
        super().__init__(self.file.dict)

    def reset(self):
        self.permissions = self.file.dict
        super().reset()

    def read(self):
        return self.file.read()

    def write(self, new_permissions, dry=False):
        if self.file.write(new_permissions, dry=dry) and not dry:
            self.reset()


class OAuthMiddleware(BaseHTTPMiddleware):
    """Gate all routes behind OAuth.

    Arguments:
        app: The application this middleware is added to.
        oauth: The OAuth object.
        is_authorized: A function that takes (user, path) and returns whether the
            given user can access the given path. In all cases, the user must identify
            themselves through OAuth prior to this. The user's email is in `user["email"]`.
            The default function always returns True.
    """

    def __init__(self, app, oauth, is_authorized=lambda user, path: True):
        super().__init__(app)
        self.oauth = oauth
        self.router = app
        self.is_authorized = is_authorized
        while not hasattr(self.router, "add_route"):
            self.router = self.router.app
        self.add_routes()

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
            content = H.body(
                H.h2("Forbidden"),
                H.p("User ", H.b(user["email"]), " cannot access this page."),
                H.a("Logout", href="/_/logout"),
            )
            return HTMLResponse(str(content), status_code=403)
        else:
            return await call_next(request)
