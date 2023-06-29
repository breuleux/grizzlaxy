from hrepr import H
from ovld import ovld
from starbear.serve import MotherBear
from starlette.responses import HTMLResponse

from .utils import here

template = here() / "index-template.html"


class Index:
    async def __call__(self, scope, receive, send):
        app = scope["app"]
        content = render("/", app.map, restrict=scope["root_path"])
        content = H.div(
            H.h2("Application index"),
            content,
        )
        html = template.read_text()
        html = html.replace("{{content}}", str(content))
        response = HTMLResponse(html)
        await response(scope, receive, send)


def render(base_path, obj, *, restrict):
    if not base_path.startswith(restrict) and not restrict.startswith(base_path):
        return None
    return _render(base_path, obj, restrict=restrict)


@ovld
def _render(base_path: str, d: dict, *, restrict):
    def _join(p):
        return f"{base_path.rstrip('/')}{p.rstrip('/')}"

    results = H.table()
    for path, value in d.items():
        real_path = _join(path) or "/"
        description = render(real_path, value, restrict=restrict)
        if description is not None:
            results = results(
                H.tr(
                    H.td["url"](H.a(path, href=real_path)),
                    H.td(description),
                )
            )
    return results


@ovld
def _render(base_path: str, mb: MotherBear, *, restrict):
    return H.span(mb.fn.__doc__)


@ovld
def _render(base_path: str, idx: Index, *, restrict):
    return None


@ovld
def _render(base_path: str, obj: object, *, restrict):
    return H.span(str(obj))
