"""Typed access to config.yaml.

Kept dependency-light (PyYAML only) so `fetch` can run before the scientific
stack is installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Aoi:
    crs: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    resolution: float
    buffer_m: float

    @property
    def crs_code(self) -> int:
        return int(self.crs.split(":")[1])

    @property
    def width_px(self) -> int:
        return int(round((self.xmax - self.xmin) / self.resolution))

    @property
    def height_px(self) -> int:
        return int(round((self.ymax - self.ymin) / self.resolution))

    def __post_init__(self) -> None:
        if self.xmin >= self.xmax or self.ymin >= self.ymax:
            raise ValueError(
                f"empty AOI: {self.xmin},{self.ymin} -> {self.xmax},{self.ymax}. "
                "S-JTSK coordinates over Czechia are negative — check the signs."
            )


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]
    root: Path

    @property
    def aoi(self) -> Aoi:
        a = self.raw["aoi"]
        return Aoi(
            crs=a["crs"],
            xmin=float(a["xmin"]),
            ymin=float(a["ymin"]),
            xmax=float(a["xmax"]),
            ymax=float(a["ymax"]),
            resolution=float(a["resolution"]),
            buffer_m=float(a["buffer_m"]),
        )

    @property
    def sources(self) -> dict[str, Any]:
        return self.raw["sources"]

    @property
    def sun(self) -> dict[str, Any]:
        return self.raw["sun"]

    @property
    def observer(self) -> dict[str, Any]:
        return self.raw["observer"]

    @property
    def far_field(self) -> dict[str, Any]:
        return self.raw["far_field"]

    @property
    def output(self) -> dict[str, Any]:
        return self.raw["output"]

    @property
    def out_dir(self) -> Path:
        """Output directory, resolved relative to the CONFIG FILE's directory.

        Mind the trap: `root` is the config's parent, so `config.yaml` at the
        repo root writes `data/` there, but `configs/north.yaml` with
        `dir: data_north` writes `configs/data_north/`. Discovered the hard
        way; kept as-is because a region's config moving with its data is
        defensible and the caches were already laid out this way.
        """
        p = self.root / self.output["dir"]
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def raw_dir(self) -> Path:
        p = self.out_dir / "raw"
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path).resolve()
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Config(raw=raw, root=path.parent)
