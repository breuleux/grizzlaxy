"""Find spacebears/routes in a file or directory"""

import importlib
import pkgutil
import runpy
from functools import reduce
from pathlib import Path

from ovld import ovld
from starbear.serve import AbstractBear
from starlette.routing import Mount, Route

from .index import Index


def collect_routes_from_module(mod):
    def process_module(path, submod, ispkg):
        subroutes = getattr(submod, "ROUTES", None)
        if subroutes is not None:
            routes[path] = subroutes
        elif ispkg:
            routes[path] = collect_routes_from_module(submod)

    locations = mod.__spec__.submodule_search_locations
    routes = {}
    if locations is None:
        process_module("/", mod, False)
    else:
        for info in pkgutil.iter_modules(locations, prefix=f"{mod.__name__}."):
            submod = importlib.import_module(info.name)
            path = f"/{submod.__name__.split('.')[-1]}/"
            process_module(path, submod, info.ispkg)

    if "/index/" not in routes.keys():
        routes["/index/"] = Index()

    return routes


def _flatten(routes):
    return reduce(list.__iadd__, routes, [])


def _mount(path, routes):
    if path == "/":
        return routes
    else:
        return [Mount(path, routes=routes)]


def collect_routes(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Cannot find route from non-existent path: {path}")

    route_path = f"/{path.stem}"

    if path.is_dir():
        mod = importlib.import_module(path.stem)
        return {"/": collect_routes_from_module(mod)}

    else:
        glb = runpy.run_path(path)
        return {route_path: glb["ROUTES"]}


@ovld
def compile_routes(path, routes: dict):
    routes = dict(routes)
    if "/" not in routes:
        if "/index/" in routes:
            routes["/"] = routes["/index/"]
        else:
            routes["/"] = Index()
    return _mount(
        path,
        _flatten([compile_routes(path2, route) for path2, route in routes.items()]),
    )


@ovld
def compile_routes(path, mb: AbstractBear):  # noqa: F811
    return _mount(path, mb.routes())


@ovld
def compile_routes(path, obj: object):  # noqa: F811
    if callable(obj):
        return [Route(path, obj)]
    else:
        raise TypeError(f"Cannot compile route for {path}: {obj}")
