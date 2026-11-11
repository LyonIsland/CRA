"""Locate the separately installed, unmodified BRICKLAB snapshot."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BRICKLAB = ROOT/'tools/BRICKLAB'


def upstream():
    bridge = BRICKLAB/'isaaclab-bridge'
    if not (bridge/'manual_renderer.py').is_file():
        raise RuntimeError('BRICKLAB is not installed. Run setup-bricklab.ps1 -Source <zip-or-directory>.')
    if str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))
    return bridge


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result
