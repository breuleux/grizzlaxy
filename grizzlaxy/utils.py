from functools import reduce
import json
import sys
from ovld import ovld
from pathlib import Path


class UsageError(Exception):
    pass


class ConfigFile:
    def __init__(self, file):
        self.dict = None
        self.file = file
        if not self.file.exists():
            raise FileNotFoundError(self.file)
        self.reset()

    def reset(self):
        self.dict = self.parse(self.read())

    def read(self):
        return self.file.read_text()

    def write(self, new_content, dry=False):
        if dry:
            # Check that the new content is valid
            self.parse(new_content)
        else:
            previous = self.read()
            self.file.write_text(new_content)
            try:
                self.reset()
            except Exception:
                self.file.write_text(previous)
                self.reset()
                raise
        return True


class JSONFile(ConfigFile):
    def parse(self, content):
        return json.loads(content)


class YAMLFile(ConfigFile):
    def parse(self, content):
        import yaml

        return yaml.safe_load(content)


extensions_map = {
    ".json": JSONFile,
    ".yaml": YAMLFile,
    ".yml": YAMLFile,
}


@ovld  # noqa: F811
def merge(d1: dict, d2):
    rval = type(d1)()
    for k, v in d1.items():
        if k in d2:
            v2 = d2[k]
            rval[k] = merge(v, v2)
        else:
            rval[k] = v
    for k, v in d2.items():
        if k not in d1:
            rval[k] = v
    return rval


@ovld  # noqa: F811
def merge(l1: list, l2: list):
    return l2


@ovld  # noqa: F811
def merge(l1: list, d: dict):
    if "append" in d:
        return l1 + d["append"]
    else:
        raise TypeError("Cannot merge list and dict unless dict has 'append' key")


@ovld  # noqa: F811
def merge(a: object, b):
    if hasattr(a, "__merge__"):
        return a.__merge__(b)
    else:
        return b


@ovld
def absolutize_paths(d: dict, dir: Path):
    return {k: absolutize_paths(v, dir) for k, v in d.items()}


@ovld
def absolutize_paths(l: list, dir: Path):
    return [absolutize_paths(v, dir) for v in l]


@ovld
def absolutize_paths(s: str, dir: Path):
    if s.startswith("./") and s != "./":
        return str(dir / s)
    else:
        return s


@ovld
def absolutize_paths(obj: object, dir: Path):
    return obj


def make_config(config_file):
    config_file = Path(config_file)
    suffix = config_file.suffix
    cls = extensions_map.get(suffix, None)
    if cls is None:
        raise UsageError(f"Unknown config file extension: {suffix}")
    else:
        return cls(config_file)


def parse_config():
    return make_config().dict


def read_config(config_file):
    config_file = Path(config_file)
    suffix = config_file.suffix
    if suffix == ".json":
        with open(config_file) as f:
            cfg = json.load(f)
    elif suffix in (".yml", ".yaml"):
        import yaml

        with open(config_file) as f:
            cfg = yaml.safe_load(f)
    else:
        raise UsageError(f"Unknown config file extension: {suffix}")
    return absolutize_paths(cfg, config_file.parent.absolute())


def read_configs(*sources):
    results = [read_config(source) for source in sources]
    return reduce(merge, results, {})


def here(depth=1):
    fr = sys._getframe(depth)
    filename = fr.f_code.co_filename
    return Path(filename).parent
