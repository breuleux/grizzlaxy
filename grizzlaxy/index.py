from pathlib import Path

from hrepr import H
from ovld import ovld
from starbear.serve import LoneBear
from starbear.templating import template

from .utils import here


class Index(LoneBear):
    hidden = True

    def __init__(self, template=here() / "index-template.html"):
        super().__init__(self.run)
        self.location = template.parent if isinstance(template, Path) else None
        self.template = template

    async def run(self, request):
        scope = request.scope
        app = scope["app"]
        root_path = scope["root_path"]
        content = render("/", app.map, restrict=root_path)
        if content is None:
            content = render("/", app.map, restrict="/".join(root_path.split("/")[:-1]))
        return template(
            self.template,
            body=content or "",
            _asset=lambda name: self.location / name,
        )


def render(base_path, obj, *, restrict):
    if not base_path.startswith(restrict) and not restrict.startswith(base_path):
        return None
    return _render(base_path, obj, restrict=restrict)


@ovld
def _render(base_path: str, d: dict, *, restrict):
    def _join(p):
        return f"{base_path.rstrip('/')}{p.rstrip('/')}"

    has_results = False
    results = H.table()
    for path, value in d.items():
        real_path = _join(path) or "/"
        description = render(real_path, value, restrict=restrict)
        if description is not None:
            has_results = True
            results = results(
                H.tr(
                    H.td["url"](H.a(path, href=real_path)),
                    H.td(description),
                )
            )
    return results if has_results else None


@ovld
def _render(base_path: str, obj: object, *, restrict):
    if getattr(obj, "hidden", False):
        return None
    obj = getattr(obj, "__doc__", obj)
    return H.span("No description." if obj is None else str(obj))
