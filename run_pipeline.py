"""
run_pipeline.py — Full pipeline entry point
Chains: extract → map → report in a single command.

Usage:
    python run_pipeline.py --mock              # demo with synthetic data
    python run_pipeline.py --config config.yaml   # live broker
    python run_pipeline.py --config config.yaml --vpn ACME_PROD
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="ACME Solace AI — full pipeline")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--vpn", default=None)
    parser.add_argument("--mock", action="store_true",
                        help="Use synthetic data (no broker required)")
    parser.add_argument("--skip-extract", default=None, metavar="FILE",
                        help="Skip extraction; load existing JSON from FILE")
    parser.add_argument("--skip-map", default=None, metavar="FILE",
                        help="Skip mapping; load existing mapped JSON from FILE")
    args = parser.parse_args()

    # Step 1: Extract
    if args.skip_extract:
        extract_file = args.skip_extract
        print(f"Skipping extraction, using: {extract_file}")
    else:
        print("\n=== Step 1: SEMP Extraction ===")
        from src import semp_extractor
        sys.argv = ["semp_extractor"]
        if args.mock:
            sys.argv.append("--mock")
        else:
            sys.argv += ["--config", args.config]
        if args.vpn:
            sys.argv += ["--vpn", args.vpn]
        extract_file = semp_extractor.main()

    # Step 2: Map taxonomy
    if args.skip_map:
        mapped_file = args.skip_map
        print(f"Skipping mapping, using: {mapped_file}")
    else:
        print("\n=== Step 2: Taxonomy Mapping ===")
        from src import taxonomy_mapper
        sys.argv = ["taxonomy_mapper", "--input", extract_file]
        if not Path(args.config).exists():
            pass  # mapper uses defaults
        else:
            sys.argv += ["--config", args.config]
        mapped_file = taxonomy_mapper.main()

    # Step 3: Report
    print("\n=== Step 3: Excel Report ===")
    from src import report_generator
    sys.argv = ["report_generator", "--input", mapped_file]
    if Path(args.config).exists():
        sys.argv += ["--config", args.config]
    report_file = report_generator.main()

    print(f"\n✓ Pipeline complete.")
    print(f"  Extract: {extract_file}")
    print(f"  Mapped:  {mapped_file}")
    print(f"  Report:  {report_file}")


if __name__ == "__main__":
    main()
