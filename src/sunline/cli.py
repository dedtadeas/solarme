"""Command line entry point: `sunline <stage>`."""

from __future__ import annotations

import argparse
import sys

from .config import load_config

STAGES = ("fetch", "sun", "eclipse", "composite", "publish", "publish-max", "all")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sunline",
        description="Where a low sun is actually visible, and where it is blocked.",
    )
    p.add_argument("stage", choices=STAGES, help="pipeline stage to run")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument(
        "--block-m",
        type=float,
        default=4000.0,
        help="sweep block size in metres (composite only; lower it if RAM is tight)",
    )
    p.add_argument("--workers", type=int, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    cfg = load_config(args.config)

    if args.stage in ("fetch", "all"):
        from .fetch import fetch_layer

        for layer in ("surface", "terrain"):
            fetch_layer(cfg, layer)

    if args.stage == "sun":
        from .sun import describe

        print(describe(cfg))
        return 0

    if args.stage == "eclipse":
        from .sun import eclipse_circumstances

        ec = eclipse_circumstances(cfg)
        if ec is None:
            print("no solar eclipse at this location on the configured date")
            return 0
        print(f"first contact   {ec.first}")
        print(f"maximum         {ec.maximum}")
        print(f"last contact    {ec.last}")
        print(f"sunset          {ec.sunset:%H:%M:%S}")
        print(f"magnitude       {ec.magnitude:.3f} of the solar diameter")
        print(f"obscuration     {ec.obscuration:.3f} of the solar area")
        if not ec.maximum_is_visible:
            print("  !! maximum happens below the horizon here")
        if ec.ends_after_sunset:
            print("  note: the eclipse outlasts sunset — last contact is never visible")
        return 0

    if args.stage in ("composite", "all"):
        from .composite import run as composite_run

        composite_run(cfg, block_m=args.block_m, workers=args.workers)

    if args.stage in ("publish", "all"):
        from .publish import run as publish_run

        publish_run(cfg)

    if args.stage in ("publish-max", "all"):
        from .publish import run_max

        run_max(cfg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
