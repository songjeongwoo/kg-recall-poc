"""NHTSA 리콜 원본(탭 구분)에서 대상 브랜드만 골라 캠페인 단위 JSONL로 묶는다.

원본 한 행은 '캠페인 x 브랜드/차종/연식 x 부품' 조합이다. 같은 캠페인의 행을 합쳐
캠페인 하나가 한 줄이 되게 만든다.

    python -m kgpoc.prepare --raw data/raw/FLAT_RCL_POST_2010.txt --out data/processed/campaigns.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

# RCL.txt 필드 순서(1부터 셈)를 0부터 센 위치로 옮김
F = {
    "RECORD_ID": 0, "CAMPNO": 1, "MAKETXT": 2, "MODELTXT": 3, "YEARTXT": 4, "MFGCAMPNO": 5,
    "COMPNAME": 6, "MFGNAME": 7, "BGMAN": 8, "ENDMAN": 9, "RCLTYPECD": 10, "POTAFF": 11,
    "ODATE": 12, "INFLUENCED_BY": 13, "MFGTXT": 14, "RCDATE": 15, "DATEA": 16, "RPNO": 17,
    "FMVSS": 18, "DESC_DEFECT": 19, "CONEQUENCE_DEFECT": 20, "CORRECTIVE_ACTION": 21,
    "NOTES": 22, "RCL_CMPT_ID": 23, "MFR_COMP_NAME": 24, "MFR_COMP_DESC": 25,
    "MFR_COMP_PTNO": 26, "DO_NOT_DRIVE": 27, "PARK_OUTSIDE": 28,
}
DEFAULT_MAKES = ("HYUNDAI", "KIA", "GENESIS")


def _yes(v: str) -> bool | None:
    v = v.strip().lower()
    return True if v == "yes" else False if v == "no" else None


def load(raw: Path, makes: tuple[str, ...]) -> list[dict]:
    camps: dict[str, dict] = {}
    vehicles: dict[str, set] = defaultdict(set)
    comps: dict[str, set] = defaultdict(set)
    parts: dict[str, set] = defaultdict(set)
    # 원본은 Latin-1로 읽어야 깨지지 않는다(UTF-8 아닌 바이트가 섞여 있음)
    with raw.open(encoding="latin-1", newline="") as f:
        for line in f:
            p = line.rstrip("\r\n").split("\t")
            if len(p) < 29 or p[F["MAKETXT"]].strip().upper() not in makes:
                continue
            c = p[F["CAMPNO"]].strip()
            year = p[F["YEARTXT"]].strip()
            vehicles[c].add((p[F["MAKETXT"]].strip().upper(), p[F["MODELTXT"]].strip().upper(),
                             None if year in ("", "9999") else int(year)))
            comps[c].add(p[F["COMPNAME"]].strip())
            if p[F["MFR_COMP_PTNO"]].strip():
                parts[c].add((p[F["MFR_COMP_NAME"]].strip(), p[F["MFR_COMP_PTNO"]].strip()))
            potaff = int(p[F["POTAFF"]]) if p[F["POTAFF"]].strip().isdigit() else None
            prev = camps.get(c)
            if prev is None:
                camps[c] = {
                    "campaign": c,
                    "mfg_campaign": p[F["MFGCAMPNO"]].strip(),
                    "manufacturer": p[F["MFGNAME"]].strip(),
                    "type": p[F["RCLTYPECD"]].strip(),
                    "initiated_by": p[F["INFLUENCED_BY"]].strip(),
                    "report_received": p[F["RCDATE"]].strip(),
                    "owner_notified": p[F["ODATE"]].strip(),
                    "fmvss": p[F["FMVSS"]].strip(),
                    "potentially_affected": potaff,
                    "do_not_drive": _yes(p[F["DO_NOT_DRIVE"]]),
                    "park_outside": _yes(p[F["PARK_OUTSIDE"]]),
                    "defect": p[F["DESC_DEFECT"]].strip(),
                    "consequence": p[F["CONEQUENCE_DEFECT"]].strip(),
                    "corrective": p[F["CORRECTIVE_ACTION"]].strip(),
                    "notes": p[F["NOTES"]].strip(),
                }
            elif potaff is not None:
                prev["potentially_affected"] = max(prev["potentially_affected"] or 0, potaff)

    out = []
    for c, d in sorted(camps.items(), key=lambda kv: (kv[1]["report_received"], kv[0])):
        d["vehicles"] = [{"make": m, "model": mo, "year": y}
                         for m, mo, y in sorted(vehicles[c], key=lambda t: (t[0], t[1], t[2] or 0))]
        d["components"] = sorted(comps[c])
        d["parts"] = [{"name": n, "part_no": pn} for n, pn in sorted(parts[c])]
        out.append(d)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/raw/FLAT_RCL_POST_2010.txt"))
    ap.add_argument("--out", type=Path, default=Path("data/processed/campaigns.jsonl"))
    ap.add_argument("--makes", default=",".join(DEFAULT_MAKES))
    a = ap.parse_args()
    rows = load(a.raw, tuple(m.strip().upper() for m in a.makes.split(",")))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_veh = sum(len(r["vehicles"]) for r in rows)
    print(f"campaigns={len(rows)} vehicle_rows={n_veh} -> {a.out}")


if __name__ == "__main__":
    main()
