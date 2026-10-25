"""NHTSA 리콜 원본 파일과 데이터 사전을 data/raw/에 내려받는다.

    python -m kgpoc.download
"""
from __future__ import annotations

import urllib.request
import zipfile

from . import ROOT

BASE = "https://static.nhtsa.gov/odi/ffdd/rcl/"
FILES = ["RCL.txt", "FLAT_RCL_POST_2010.zip"]


def main() -> None:
    raw = ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dest = raw / name
        print(f"GET {BASE + name}")
        urllib.request.urlretrieve(BASE + name, dest)
        print(f"  -> {dest} ({dest.stat().st_size:,} bytes)")
    with zipfile.ZipFile(raw / "FLAT_RCL_POST_2010.zip") as z:
        z.extractall(raw)
    print("extracted FLAT_RCL_POST_2010.txt")


if __name__ == "__main__":
    main()
