"""Find spacebears/routes in a file or directory"""

import importlib
import pkgutil
import runpy
from pathlib import Path

from starbear.serve import MotherBear
from starlette.routing import Mount


def collect_routes_from_module(mod):
    location = Path(mod.__file__).parent
    routes = []
    for info in pkgutil.walk_packages([location], prefix=f"{mod.__name__}."):
        submod = importlib.import_module(info.name)
        path = f"/{submod.__name__.split('.')[-1]}/"
        subroutes = getattr(submod, "ROUTES", None)
        if isinstance(subroutes, MotherBear):
            subroutes = subroutes.routes()
        if subroutes is not None:
            routes.append(Mount(path, routes=subroutes))
        elif info.ispkg:
            routes.append(Mount(path, routes=collect_routes_from_module(submod)))
    return routes


def collect_routes(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Cannot find route from non-existent path: {path}")

    route_path = f"/{path.stem}"

    if path.is_dir():
        mod = importlib.import_module(path.stem)
        return Mount("/", routes=collect_routes_from_module(mod))

    else:
        glb = runpy.run_path(path)
        return Mount(route_path, glb["ROUTES"])
