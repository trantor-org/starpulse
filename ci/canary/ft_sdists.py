"""Fetch the locked aioquic and pylsqpack sdists and patch them to build on free-threaded 3.14t: drop the limited API
(abi3 wheels cannot load there) and declare the module GIL-free. Usage: ft_sdists.py <uv.lock> <outdir>."""

import hashlib
import re
import sys
import tarfile
import tomllib
import urllib.request
from pathlib import Path

GIL_FREE = "\n#ifdef Py_GIL_DISABLED\n    PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED);\n#endif"
LIMITED_API = re.compile(r".*(Py_LIMITED_API|py_limited_api|bdist_wheel).*\n")

lock, out = tomllib.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2])
for pkg in (p for p in lock["package"] if p["name"] in ("aioquic", "pylsqpack")):
    sdist = pkg["sdist"]
    data = urllib.request.urlopen(sdist["url"]).read()
    assert "sha256:" + hashlib.sha256(data).hexdigest() == sdist["hash"], pkg["name"]
    archive = out / f"{pkg['name']}.tar.gz"
    archive.write_bytes(data)
    with tarfile.open(archive) as tar:
        tar.extractall(out, filter="data")
    src = out / f"{pkg['name']}-{pkg['version']}"
    src.rename(out / pkg["name"])
    setup = out / pkg["name"] / "setup.py"
    setup.write_text(LIMITED_API.sub("", setup.read_text()))
    for c in (out / pkg["name"] / "src").rglob("*.c"):
        text = c.read_text()
        if "PyModule_Create(&moduledef);" in text:
            c.write_text(text.replace("    if (m == NULL)\n        return NULL;", "    if (m == NULL)\n        return NULL;" + GIL_FREE, 1))
