#!/usr/bin/python3
"""Stage this lab's measured firmware bytes into the disposable root only."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
here = Path(__file__).resolve().parent
runpy.run_path(str(here / 'guard-device.py'))
loader = SourceFileLoader('firmware', '/usr/libexec/pocketfed-fingerprint-firmware')
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
module.BUILD = 'google/sargo/sargo:12/SP2A.220505.002/8353555:user/release-keys'
module.MANIFEST = here / 'firmware-manifest.json'
sys.argv = ['lab-firmware', '--extract']
module.main()
