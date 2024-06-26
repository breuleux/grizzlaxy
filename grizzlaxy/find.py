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
        cls = getattr(obj, "route_class", Route)
        route_parameters = getattr(obj, "route_parameters", {})
        return [cls(path, obj, **route_parameters)]
    else:
        raise TypeError(f"Cannot compile route for {path}: {obj}")


@ovld
def collect_locations(routes: dict):  # noqa: F811
    rval = set()
    for subroutes in routes.values():
        rval.update(collect_locations(subroutes))
    return rval


@ovld
def collect_locations(b: AbstractBear):  # noqa: F811
    return collect_locations(getattr(b, "fn", None))


@ovld
def collect_locations(obj: object):  # noqa: F811
    if hasattr(obj, "__globals__"):
        loc = obj.__globals__.get("__file__", None)
        return {Path(loc).parent} if loc else set()
    elif hasattr(obj, "__call__"):
        return collect_locations(obj.__call__)
    else:
        return set()
