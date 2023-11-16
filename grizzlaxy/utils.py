import json
import sys
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
            return json.load(f)
    elif suffix in (".yml", ".yaml"):
        import yaml

        with open(config_file) as f:
            return yaml.safe_load(f)
    else:
        raise UsageError(f"Unknown config file extension: {suffix}")


def here(depth=1):
    fr = sys._getframe(depth)
    filename = fr.f_code.co_filename
    return Path(filename).parent
