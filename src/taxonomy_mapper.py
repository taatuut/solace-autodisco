"""
taxonomy_mapper.py — Step 2
Maps extracted SEMP data to client applications and business objects
using configurable topic taxonomy rules.

Topic convention assumed (configurable in config.yaml):
  <prefix>/<environment>/<domain>/<businessObject>/<eventType>/<version>
  Example: acme/prod/sales/Order/Created/v1

Workflow:
  1. Load raw SEMP extract JSON
  2. Collect all unique topics (from queue subscriptions + topic endpoints)
  3. Parse topics according to taxonomy level definitions in config
  4. Auto-derive mapping rules (stored in output/taxonomy_rules.yaml)
  5. Map client usernames -> topics they publish/subscribe to
  6. Output enriched JSON ready for report generation

Usage:
    python src/taxonomy_mapper.py [--config config.yaml] [--input <semp_extract.json>] [--mock]
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Topic parser
# ---------------------------------------------------------------------------

class TopicParser:
    """Parse a topic string into semantic segments based on configured levels."""

    def __init__(self, levels: dict, separator: str = "/"):
        # levels: {0: "prefix", 1: "environment", ...}
        self.levels = {int(k): v for k, v in levels.items()}
        self.separator = separator

    def parse(self, topic: str) -> dict:
        """Return a dict of {levelName: value} for a given topic string."""
        parts = topic.split(self.separator)
        parsed = {"_raw": topic, "_segments": parts}
        for idx, label in self.levels.items():
            parsed[label] = parts[idx] if idx < len(parts) else None
        parsed["_wildcardDepth"] = topic.count(">") + topic.count("*")
        return parsed

    def is_wildcard(self, topic: str) -> bool:
        return ">" in topic or "*" in topic


# ---------------------------------------------------------------------------
# Rule derivation
# ---------------------------------------------------------------------------

def derive_rules(parsed_topics: list[dict], levels: dict) -> dict:
    """
    Auto-derive taxonomy rules from observed topic patterns.

    Returns a rules dict:
      environments: [list of observed env values]
      domains: [list of observed domain values]
      businessObjects: [list of observed BO values]
      eventTypes: [list of observed event type values]
      topicPatternToBusinessObject: {topic_prefix -> businessObject}
      domainToApplicationGroup: {domain -> [applications]}
    """
    rules = {
        "derivedAt": datetime.now().isoformat(),
        "note": "Auto-derived from SEMP extraction. Review and extend manually.",
        "environments": [],
        "domains": [],
        "businessObjects": [],
        "eventTypes": [],
        "topicPatternToBusinessObject": {},
        "domainToApplicationGroup": {},
    }

    # Collect unique values per level (skip wildcards)
    level_values = defaultdict(set)
    for pt in parsed_topics:
        if pt.get("_wildcardDepth", 0) == 0:
            for lvl_name in levels.values():
                val = pt.get(lvl_name)
                if val:
                    level_values[lvl_name].add(val)

    rules["environments"] = sorted(level_values.get("environment", []))
    rules["domains"] = sorted(level_values.get("domain", []))
    rules["businessObjects"] = sorted(level_values.get("businessObject", []))
    rules["eventTypes"] = sorted(level_values.get("eventType", []))

    # Build topic prefix -> businessObject mapping
    sep = "/"
    for pt in parsed_topics:
        if pt.get("_wildcardDepth", 0) == 0:
            segs = pt.get("_segments", [])
            bo = pt.get("businessObject")
            if bo and len(segs) >= 4:
                # Key on first 4 segments (up to businessObject level)
                prefix = sep.join(segs[:4])
                rules["topicPatternToBusinessObject"][prefix] = bo

    return rules


# ---------------------------------------------------------------------------
# Application <-> topic mapping
# ---------------------------------------------------------------------------

def map_applications(vpn_data: list[dict], parser: TopicParser) -> list[dict]:
    """
    For each VPN, build application records combining:
    - clientUsername (identity/config)
    - connected clients (runtime)
    - queue bindings (inferred publish/subscribe)
    """
    applications = []

    for vpn in vpn_data:
        vpn_name = vpn["msgVpnName"]

        # Index: username -> client_username config record
        username_map = {
            u["clientUsername"]: u
            for u in vpn.get("clientUsernames", [])
        }

        # Index: username -> list of runtime client connections
        connected_map = defaultdict(list)
        for c in vpn.get("connectedClients", []):
            connected_map[c.get("clientUsername", "")].append(c)

        # Index: queue -> subscriptions
        queue_subs_map = {}
        for q in vpn.get("queues", []):
            queue_subs_map[q["queueName"]] = {
                "queue": q,
                "subscriptions": [
                    s["subscriptionTopic"]
                    for s in q.get("_subscriptions", [])
                ],
            }

        # For each known username, build an application record
        all_usernames = set(username_map.keys()) | set(connected_map.keys())
        for username in all_usernames:
            cu = username_map.get(username, {})
            connections = connected_map.get(username, [])

            # Find queues owned by or bound to this username
            owned_queues = [
                q for q in vpn.get("queues", [])
                if q.get("owner") == username
            ]

            # Derive subscribed topics from queue subscriptions
            subscribed_topics = []
            for oq in owned_queues:
                subs = queue_subs_map.get(oq["queueName"], {}).get("subscriptions", [])
                subscribed_topics.extend(subs)

            # Parse subscribed topics
            parsed_subs = [parser.parse(t) for t in subscribed_topics]

            # Infer business objects consumed
            business_objects_consumed = list({
                p.get("businessObject") for p in parsed_subs
                if p.get("businessObject") and not parser.is_wildcard(p["_raw"])
            })

            # Infer domains
            domains = list({
                p.get("domain") for p in parsed_subs
                if p.get("domain") and not parser.is_wildcard(p["_raw"])
            })

            app = {
                "msgVpnName": vpn_name,
                "applicationId": username,
                "enabled": cu.get("enabled", True),
                "clientProfileName": cu.get("clientProfileName"),
                "aclProfileName": cu.get("aclProfileName"),
                "ownedQueues": [q["queueName"] for q in owned_queues],
                "subscribedTopics": subscribed_topics,
                "parsedSubscriptions": parsed_subs,
                "businessObjectsConsumed": business_objects_consumed,
                "domainsInvolved": domains,
                "activeConnections": len(connections),
                "connectionDetails": connections,
            }
            applications.append(app)

    return applications


# ---------------------------------------------------------------------------
# Business object catalogue
# ---------------------------------------------------------------------------

def build_bo_catalogue(parsed_topics: list[dict]) -> list[dict]:
    """Aggregate unique business objects with their observed event types and topics."""
    bo_map: dict[str, dict] = {}

    for pt in parsed_topics:
        bo = pt.get("businessObject")
        if not bo or parser_is_wildcard(pt):
            continue
        domain = pt.get("domain", "unknown")
        env = pt.get("environment", "unknown")
        event_type = pt.get("eventType", "unknown")
        version = pt.get("version", "unknown")
        key = f"{domain}/{bo}"

        if key not in bo_map:
            bo_map[key] = {
                "businessObject": bo,
                "domain": domain,
                "environments": set(),
                "eventTypes": set(),
                "versions": set(),
                "topics": [],
            }
        bo_map[key]["environments"].add(env)
        bo_map[key]["eventTypes"].add(event_type)
        bo_map[key]["versions"].add(version)
        if pt["_raw"] not in bo_map[key]["topics"]:
            bo_map[key]["topics"].append(pt["_raw"])

    # Serialise sets
    catalogue = []
    for entry in bo_map.values():
        entry["environments"] = sorted(entry["environments"])
        entry["eventTypes"] = sorted(entry["eventTypes"])
        entry["versions"] = sorted(entry["versions"])
        catalogue.append(entry)

    return sorted(catalogue, key=lambda x: (x["domain"], x["businessObject"]))


def parser_is_wildcard(pt: dict) -> bool:
    return pt.get("_wildcardDepth", 0) > 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    arg_parser = argparse.ArgumentParser(
        description="Map SEMP extract to configured topic taxonomy"
    )
    arg_parser.add_argument("--config", default="config.yaml")
    arg_parser.add_argument("--input", default=None,
                            help="Path to semp_extract JSON file. "
                                 "If omitted, uses most recent file in output/raw/")
    arg_parser.add_argument("--mock", action="store_true",
                            help="Generate from mock data (run semp_extractor --mock first)")
    args = arg_parser.parse_args()

    # Load config — falls back to the committed config.example.yaml (single
    # source of truth for taxonomy defaults) when config.yaml doesn't exist yet.
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        cfg_path = cfg_path.parent / "config.example.yaml"
    with open(cfg_path) as f:
        config = yaml.safe_load(f)

    tax_cfg = config.get("taxonomy", {})
    levels = {int(k): v for k, v in tax_cfg.get("levels", {}).items()}
    separator = tax_cfg.get("separator", "/")
    rules_file = tax_cfg.get("rules_file", "output/taxonomy_rules.yaml")

    # Find input file
    if args.input:
        input_file = Path(args.input)
    else:
        raw_dir = Path(config.get("output", {}).get("raw_dir", "output/raw"))
        candidates = sorted(raw_dir.glob("semp_extract_*.json"), reverse=True)
        if not candidates:
            print(f"[ERROR] No semp_extract_*.json files found in {raw_dir}")
            print("Run: python src/semp_extractor.py --mock")
            raise SystemExit(1)
        input_file = candidates[0]

    print(f"Loading: {input_file}")
    with open(input_file) as f:
        extract = json.load(f)

    vpn_data = extract.get("vpnData", [])

    # Collect all topics
    all_topics = []
    for vpn in vpn_data:
        for q in vpn.get("queues", []):
            for sub in q.get("_subscriptions", []):
                topic = sub.get("subscriptionTopic") or sub.get("topic")
                if topic and topic not in all_topics:
                    all_topics.append(topic)

    print(f"Unique topics found: {len(all_topics)}")

    # Parse topics
    topic_parser = TopicParser(levels, separator)
    parsed_topics = [topic_parser.parse(t) for t in all_topics]

    # Derive rules
    rules = derive_rules(parsed_topics, levels)
    Path(rules_file).parent.mkdir(parents=True, exist_ok=True)
    with open(rules_file, "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)
    print(f"Taxonomy rules saved: {rules_file}")

    # Map applications
    applications = map_applications(vpn_data, topic_parser)
    print(f"Applications mapped: {len(applications)}")

    # Build business object catalogue
    bo_catalogue = build_bo_catalogue(parsed_topics)
    print(f"Business objects catalogued: {len(bo_catalogue)}")

    # Compose output
    out_dir = Path(config.get("output", {}).get("report_dir", "output/reports"))
    out_dir.mkdir(parents=True, exist_ok=True)

    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"mapped_data_{ts_str}.json"

    mapped = {
        "mappedAt": datetime.now().isoformat(),
        "sourceFile": str(input_file),
        "taxonomyLevels": levels,
        "uniqueTopics": all_topics,
        "parsedTopics": parsed_topics,
        "applications": applications,
        "businessObjectCatalogue": bo_catalogue,
        "msgVpns": extract.get("msgVpns", []),
        "vpnData": vpn_data,
    }

    with open(out_file, "w") as f:
        json.dump(mapped, f, indent=2)

    print(f"\nMapped data saved: {out_file}")
    print(f"\nSummary:")
    print(f"  Environments: {rules.get('environments')}")
    print(f"  Domains:      {rules.get('domains')}")
    print(f"  Business Objects: {rules.get('businessObjects')}")
    print(f"  Event Types:  {rules.get('eventTypes')}")

    return str(out_file)


if __name__ == "__main__":
    main()
