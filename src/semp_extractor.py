"""
semp_extractor.py — Step 1 MVP
Extracts broker metadata from Solace SEMP v2 REST API and saves raw JSON.

Extracts:
  - Message VPNs
  - Queues + their topic subscriptions
  - Client profiles
  - ACL profiles
  - Client usernames (application identities)
  - Connected clients (runtime view of active connections)
  - Topic endpoint objects (if any)

Usage:
    python src/semp_extractor.py [--config config.yaml] [--vpn <vpn>] [--mock]

Flags:
    --config  Path to config.yaml (default: config.yaml)
    --vpn     Override msg_vpn from config
    --mock    Run with synthetic sample data (no broker needed)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import yaml
from requests.auth import HTTPBasicAuth

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    console = Console()
    RICH = True
except ImportError:
    RICH = False


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        example = config_path.parent / "config.example.yaml"
        sys.exit(
            f"[ERROR] Config file not found: {path}\n"
            f"Copy {example} to {config_path} and fill in your credentials."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# SEMP v2 client
# ---------------------------------------------------------------------------

class SempClient:
    """Thin wrapper around the Solace SEMP v2 REST API."""

    def __init__(self, host: str, username: str, password: str,
                 verify_ssl: bool = True, page_size: int = 100):
        self.base_url = host.rstrip("/") + "/SEMP/v2"
        self.auth = HTTPBasicAuth(username, password)
        self.verify_ssl = verify_ssl
        self.page_size = page_size
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.verify = verify_ssl
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """Single GET request; raises on non-2xx."""
        url = self.base_url + path
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, params: Optional[dict] = None) -> list[dict]:
        """Follow SEMP pagination cursor until all records are fetched."""
        params = dict(params or {})
        params["count"] = self.page_size
        results = []
        while True:
            data = self._get(path, params)
            results.extend(data.get("data", []))
            cursor = data.get("meta", {}).get("paging", {}).get("nextPageUri")
            if not cursor:
                break
            # cursor is a full URI; extract query string
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(cursor).query)
            params = {k: v[0] for k, v in qs.items()}
        return results

    # --- Config sub-API ---

    def get_msg_vpns(self) -> list[dict]:
        return self._paginate("/config/msgVpns")

    def get_queues(self, vpn: str) -> list[dict]:
        return self._paginate(f"/config/msgVpns/{vpn}/queues")

    def get_queue_subscriptions(self, vpn: str, queue: str) -> list[dict]:
        return self._paginate(
            f"/config/msgVpns/{vpn}/queues/{requests.utils.quote(queue, safe='')}/subscriptions"
        )

    def get_client_profiles(self, vpn: str) -> list[dict]:
        return self._paginate(f"/config/msgVpns/{vpn}/clientProfiles")

    def get_acl_profiles(self, vpn: str) -> list[dict]:
        return self._paginate(f"/config/msgVpns/{vpn}/aclProfiles")

    def get_client_usernames(self, vpn: str) -> list[dict]:
        return self._paginate(f"/config/msgVpns/{vpn}/clientUsernames")

    def get_topic_endpoints(self, vpn: str) -> list[dict]:
        return self._paginate(f"/config/msgVpns/{vpn}/topicEndpoints")

    # --- Monitor sub-API (runtime state) ---

    def _paginate_monitor(self, path: str, select_fields: str) -> list[dict]:
        """Paginate a monitor endpoint; fall back to no select on 400.

        SAP AEM's SEMP implementation rejects select parameters that reference
        fields not available on that broker version. We try with select first
        (smaller payload), and silently retry without it on a 400 so the
        pipeline never hard-fails on monitor data.
        """
        try:
            return self._paginate(path, {"select": select_fields})
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                # Retry without select — accept all fields
                return self._paginate(path)
            raise

    def get_clients(self, vpn: str) -> list[dict]:
        """Currently connected clients (runtime view)."""
        return self._paginate_monitor(
            f"/monitor/msgVpns/{vpn}/clients",
            "clientName,clientUsername,remoteAddress,"
            "description,softwareVersion,platform,"
            "rxMsgCount,txMsgCount,uptime"
        )

    def get_queue_stats(self, vpn: str) -> list[dict]:
        """Queue operational stats from monitor API."""
        return self._paginate_monitor(
            f"/monitor/msgVpns/{vpn}/queues",
            "queueName,msgVpnName,bindCount,msgCount,msgSpoolUsage,"
            "rxMsgCount,txMsgCount,accessType,permission"
        )


# ---------------------------------------------------------------------------
# Mock data (--mock flag, no broker needed)
# ---------------------------------------------------------------------------

MOCK_DATA = {
    "msgVpns": [
        {"msgVpnName": "ACME_PROD", "enabled": True, "maxMsgSpoolUsage": 1500,
         "authenticationBasicEnabled": True, "tlsEnabled": True},
        {"msgVpnName": "ACME_DEV", "enabled": True, "maxMsgSpoolUsage": 500,
         "authenticationBasicEnabled": True, "tlsEnabled": False},
    ],
    "queues": {
        "ACME_PROD": [
            {"queueName": "Q.ORDER.PROCESSOR", "msgVpnName": "ACME_PROD",
             "accessType": "exclusive", "permission": "consume",
             "owner": "app_order_svc", "maxMsgSpoolUsage": 200},
            {"queueName": "Q.INVOICE.GENERATOR", "msgVpnName": "ACME_PROD",
             "accessType": "exclusive", "permission": "consume",
             "owner": "app_finance_svc", "maxMsgSpoolUsage": 100},
            {"queueName": "Q.INVENTORY.SYNC", "msgVpnName": "ACME_PROD",
             "accessType": "non-exclusive", "permission": "consume",
             "owner": "app_wms", "maxMsgSpoolUsage": 300},
        ],
        "ACME_DEV": [
            {"queueName": "Q.ORDER.PROCESSOR.DEV", "msgVpnName": "ACME_DEV",
             "accessType": "exclusive", "permission": "consume",
             "owner": "app_order_svc", "maxMsgSpoolUsage": 50},
        ],
    },
    "queueSubscriptions": {
        "ACME_PROD/Q.ORDER.PROCESSOR": [
            {"subscriptionTopic": "acme/prod/sales/Order/Created/v1"},
            {"subscriptionTopic": "acme/prod/sales/Order/Updated/v1"},
            {"subscriptionTopic": "acme/prod/sales/Order/Cancelled/v1"},
        ],
        "ACME_PROD/Q.INVOICE.GENERATOR": [
            {"subscriptionTopic": "acme/prod/sales/Order/Created/v1"},
            {"subscriptionTopic": "acme/prod/finance/Invoice/Requested/v1"},
        ],
        "ACME_PROD/Q.INVENTORY.SYNC": [
            {"subscriptionTopic": "acme/prod/warehouse/Stock/Updated/v1"},
            {"subscriptionTopic": "acme/prod/warehouse/Stock/Reserved/v1"},
            {"subscriptionTopic": "acme/prod/warehouse/Receipt/Created/v1"},
        ],
        "ACME_DEV/Q.ORDER.PROCESSOR.DEV": [
            {"subscriptionTopic": "acme/dev/sales/Order/Created/v1"},
        ],
    },
    "clientProfiles": {
        "ACME_PROD": [
            {"clientProfileName": "default", "msgVpnName": "ACME_PROD"},
            {"clientProfileName": "readonly-profile", "msgVpnName": "ACME_PROD",
             "maxConnectionCountPerClientUsername": 5},
            {"clientProfileName": "publisher-profile", "msgVpnName": "ACME_PROD",
             "maxConnectionCountPerClientUsername": 10},
        ],
        "ACME_DEV": [
            {"clientProfileName": "default", "msgVpnName": "ACME_DEV"},
        ],
    },
    "aclProfiles": {
        "ACME_PROD": [
            {"aclProfileName": "default", "msgVpnName": "ACME_PROD",
             "clientConnectDefaultAction": "allow",
             "publishTopicDefaultAction": "disallow",
             "subscribeTopicDefaultAction": "disallow"},
            {"aclProfileName": "order-svc-acl", "msgVpnName": "ACME_PROD",
             "clientConnectDefaultAction": "allow",
             "publishTopicDefaultAction": "disallow",
             "subscribeTopicDefaultAction": "disallow"},
        ],
        "ACME_DEV": [
            {"aclProfileName": "default", "msgVpnName": "ACME_DEV",
             "clientConnectDefaultAction": "allow",
             "publishTopicDefaultAction": "allow",
             "subscribeTopicDefaultAction": "allow"},
        ],
    },
    "clientUsernames": {
        "ACME_PROD": [
            {"clientUsername": "app_order_svc", "msgVpnName": "ACME_PROD",
             "enabled": True, "clientProfileName": "publisher-profile",
             "aclProfileName": "order-svc-acl"},
            {"clientUsername": "app_finance_svc", "msgVpnName": "ACME_PROD",
             "enabled": True, "clientProfileName": "publisher-profile",
             "aclProfileName": "default"},
            {"clientUsername": "app_wms", "msgVpnName": "ACME_PROD",
             "enabled": True, "clientProfileName": "readonly-profile",
             "aclProfileName": "default"},
            {"clientUsername": "app_erp_sap", "msgVpnName": "ACME_PROD",
             "enabled": True, "clientProfileName": "publisher-profile",
             "aclProfileName": "default"},
        ],
        "ACME_DEV": [
            {"clientUsername": "app_order_svc", "msgVpnName": "ACME_DEV",
             "enabled": True, "clientProfileName": "default",
             "aclProfileName": "default"},
        ],
    },
    "topicEndpoints": {"ACME_PROD": [], "ACME_DEV": []},
    "clients": {
        "ACME_PROD": [
            {"clientName": "app_order_svc#001", "clientUsername": "app_order_svc",
             "remoteAddress": "10.0.1.10", "rxMsgCount": 45230, "txMsgCount": 12100,
             "platform": "Java", "uptime": 86400},
            {"clientName": "app_erp_sap#001", "clientUsername": "app_erp_sap",
             "remoteAddress": "10.0.1.20", "rxMsgCount": 3200, "txMsgCount": 98400,
             "platform": "SAP Integration Suite", "uptime": 72000},
        ],
        "ACME_DEV": [],
    },
    "queueStats": {
        "ACME_PROD": [
            {"queueName": "Q.ORDER.PROCESSOR", "bindCount": 2, "msgCount": 0,
             "msgSpoolUsage": 0, "rxMsgCount": 45230, "txMsgCount": 45230},
            {"queueName": "Q.INVOICE.GENERATOR", "bindCount": 1, "msgCount": 3,
             "msgSpoolUsage": 1024, "rxMsgCount": 12100, "txMsgCount": 12097},
            {"queueName": "Q.INVENTORY.SYNC", "bindCount": 1, "msgCount": 0,
             "msgSpoolUsage": 0, "rxMsgCount": 98400, "txMsgCount": 98400},
        ],
        "ACME_DEV": [
            {"queueName": "Q.ORDER.PROCESSOR.DEV", "bindCount": 1, "msgCount": 0,
             "msgSpoolUsage": 0, "rxMsgCount": 100, "txMsgCount": 100},
        ],
    },
}


# ---------------------------------------------------------------------------
# Extraction orchestration
# ---------------------------------------------------------------------------

def extract_vpn(client: SempClient, vpn_name: str, log) -> dict:
    """Extract all relevant objects for one Message VPN."""
    log(f"  Extracting VPN: {vpn_name}")

    queues = client.get_queues(vpn_name)
    log(f"    Queues: {len(queues)}")

    # Enrich each queue with its topic subscriptions
    for queue in queues:
        q_name = queue["queueName"]
        subs = client.get_queue_subscriptions(vpn_name, q_name)
        queue["_subscriptions"] = subs
    log(f"    Queue subscriptions: fetched for all queues")

    client_profiles = client.get_client_profiles(vpn_name)
    log(f"    Client profiles: {len(client_profiles)}")

    acl_profiles = client.get_acl_profiles(vpn_name)
    log(f"    ACL profiles: {len(acl_profiles)}")

    client_usernames = client.get_client_usernames(vpn_name)
    log(f"    Client usernames: {len(client_usernames)}")

    topic_endpoints = client.get_topic_endpoints(vpn_name)
    log(f"    Topic endpoints: {len(topic_endpoints)}")

    # Runtime / monitor data
    try:
        connected_clients = client.get_clients(vpn_name)
        log(f"    Connected clients (runtime): {len(connected_clients)}")
    except Exception as e:
        log(f"    [WARN] Could not fetch connected clients: {e}")
        connected_clients = []

    try:
        queue_stats = client.get_queue_stats(vpn_name)
        log(f"    Queue stats (runtime): {len(queue_stats)}")
    except Exception as e:
        log(f"    [WARN] Could not fetch queue stats: {e}")
        queue_stats = []

    return {
        "msgVpnName": vpn_name,
        "queues": queues,
        "clientProfiles": client_profiles,
        "aclProfiles": acl_profiles,
        "clientUsernames": client_usernames,
        "topicEndpoints": topic_endpoints,
        "connectedClients": connected_clients,
        "queueStats": queue_stats,
    }


def extract_mock(vpn_filter: Optional[str], log) -> dict:
    """Build extraction result from MOCK_DATA."""
    log("[MOCK] Using synthetic data — no broker connection.")
    vpns = MOCK_DATA["msgVpns"]
    if vpn_filter:
        vpns = [v for v in vpns if v["msgVpnName"] == vpn_filter]

    vpn_data = []
    for vpn in vpns:
        vn = vpn["msgVpnName"]
        queues = MOCK_DATA["queues"].get(vn, [])
        for q in queues:
            key = f"{vn}/{q['queueName']}"
            q["_subscriptions"] = [
                {"subscriptionTopic": t["subscriptionTopic"]}
                for t in MOCK_DATA["queueSubscriptions"].get(key, [])
            ]
        vpn_data.append({
            "msgVpnName": vn,
            "queues": queues,
            "clientProfiles": MOCK_DATA["clientProfiles"].get(vn, []),
            "aclProfiles": MOCK_DATA["aclProfiles"].get(vn, []),
            "clientUsernames": MOCK_DATA["clientUsernames"].get(vn, []),
            "topicEndpoints": MOCK_DATA["topicEndpoints"].get(vn, []),
            "connectedClients": MOCK_DATA["clients"].get(vn, []),
            "queueStats": MOCK_DATA["queueStats"].get(vn, []),
        })

    return {
        "extractedAt": datetime.now(timezone.utc).isoformat(),
        "source": "mock",
        "msgVpns": vpns,
        "vpnData": vpn_data,
    }


def extract_live(config: dict, vpn_filter: Optional[str], log) -> dict:
    """Extract from a real Solace broker via SEMP v2."""
    semp_cfg = config["semp"]
    client = SempClient(
        host=semp_cfg["host"],
        username=semp_cfg["username"],
        password=semp_cfg["password"],
        verify_ssl=semp_cfg.get("verify_ssl", True),
        page_size=semp_cfg.get("page_size", 100),
    )

    target_vpn = vpn_filter or semp_cfg.get("msg_vpn")
    if target_vpn and target_vpn != "*":
        vpns = [{"msgVpnName": target_vpn}]
    else:
        log("Fetching all Message VPNs...")
        vpns = client.get_msg_vpns()

    log(f"Extracting {len(vpns)} VPN(s)...")
    vpn_data = []
    for vpn in vpns:
        vpn_data.append(extract_vpn(client, vpn["msgVpnName"], log))

    return {
        "extractedAt": datetime.now(timezone.utc).isoformat(),
        "source": semp_cfg["host"],
        "msgVpns": vpns,
        "vpnData": vpn_data,
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract Solace broker metadata via SEMP v2"
    )
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config.yaml (default: config.yaml)")
    parser.add_argument("--vpn", default=None,
                        help="Override msg_vpn from config (use * for all)")
    parser.add_argument("--mock", action="store_true",
                        help="Use synthetic sample data (no broker needed)")
    parser.add_argument("--output", default=None,
                        help="Override output directory")
    args = parser.parse_args()

    # Simple logging function
    def log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        if RICH:
            console.print(f"[dim]{ts}[/dim] {msg}")
        else:
            print(f"{ts} {msg}")

    log("Solace AutoDisco — SEMP Extractor v1.0")

    if args.mock:
        result = extract_mock(args.vpn, log)
        out_dir = args.output or "output/raw"
    else:
        config = load_config(args.config)
        result = extract_live(config, args.vpn, log)
        out_dir = args.output or config.get("output", {}).get("raw_dir", "output/raw")

    # Save output
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = Path(out_dir) / f"semp_extract_{ts_str}.json"
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2)

    log(f"Saved: {out_file}")

    # Summary
    vpn_count = len(result.get("msgVpns", []))
    total_queues = sum(len(v.get("queues", [])) for v in result.get("vpnData", []))
    total_subs = sum(
        len(q.get("_subscriptions", []))
        for v in result.get("vpnData", [])
        for q in v.get("queues", [])
    )
    total_usernames = sum(len(v.get("clientUsernames", [])) for v in result.get("vpnData", []))

    log(f"\nSummary:")
    log(f"  Message VPNs:       {vpn_count}")
    log(f"  Queues:             {total_queues}")
    log(f"  Topic subscriptions:{total_subs}")
    log(f"  Client usernames:   {total_usernames}")
    log(f"\nOutput: {out_file}")

    return str(out_file)


if __name__ == "__main__":
    main()
