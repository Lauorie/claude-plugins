"""CLI entry: python3 -m citation_gate [--json] <file...>."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .verify import verify_files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="citation_gate")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")

    report = verify_files(args.files)
    if args.json:
        sys.stdout.write(json.dumps(report.to_dict(), ensure_ascii=False))
    else:
        sys.stdout.write(report.render_text() + "\n")
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
