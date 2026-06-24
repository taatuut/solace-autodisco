# ACME Solace AI

Automated discovery and cataloguing of events, topics, and applications on the ACME SAP Advanced Event Mesh (AEM) / Solace platform.

## What this project does

ACME's event-driven integration landscape (SAP AEM, powered by Solace) carries business events between ERP, WMS, e-commerce, finance, and logistics applications. Without automation, there is no reliable overview of what is flowing, how it is defined, or which applications produce and consume which events.

This project automates that discovery and produces three outputs:

| Output | File | Description |
|--------|------|-------------|
| Raw broker data | `output/raw/semp_extract_*.json` | Full SEMP v2 extraction |
| Mapped & enriched data | `output/reports/mapped_data_*.json` | Topics parsed, applications identified, business objects catalogued |
| Excel report (Step 3a) | `output/reports/pvm_solace_report_*.xlsx` | Seven-sheet workbook for stakeholder review |

## Project structure

```
solace-autodisco/
├── src/
│   ├── semp_extractor.py    # Step 1: Extract from SEMP v2 API
│   ├── taxonomy_mapper.py   # Step 2: Map topics to ACME taxonomy
│   └── report_generator.py  # Step 3a: Generate Excel report
├── run_pipeline.py          # Single-command full pipeline
├── config.example.yaml      # Connection config template (copy to config.yaml)
├── requirements.txt
├── output/
│   ├── raw/                 # Raw SEMP JSON extracts (gitignored)
│   ├── reports/             # Mapped JSON + Excel reports (gitignored)
│   └── taxonomy_rules.yaml  # Auto-derived + manually maintained taxonomy rules
└── docs/
    ├── ACME Solace AI.docx    # Background and API reference
    └── ACME_Event_Governance_Roadmap_v1.0.docx  # Governance and lifecycle roadmap
```

## Quick start

### Prerequisites

```bash
# Create and activate the virtual environment (once)
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
python3 -m pip install -r requirements.txt

# Optionally, if needed upgrade pip
python3 -m pip install --upgrade pip
```

> All subsequent commands assume the venv is active (`source .venv/bin/activate`).

### Demo with mock data (no broker needed)

```bash
python3 run_pipeline.py --mock
```

This runs the full extract → map → report pipeline with synthetic data and writes the Excel report to `output/reports/`.

### Live broker

1. Copy `config.example.yaml` to `config.yaml` and fill in your SEMP credentials:
   ```yaml
   semp:
     host: "https://your-broker-host:943"
     msg_vpn: "ACME_PROD"
     username: "admin"
     password: "your-password"
   ```

2. Run:
   ```bash
   python3 run_pipeline.py --config config.yaml
   ```

3. Or target a specific VPN:
   ```bash
   python3 run_pipeline.py --config config.yaml --vpn ACME_PROD
   ```

### Running steps individually

```bash
# Step 1 only
python3 src/semp_extractor.py --mock

# Step 2 only (uses most recent raw extract)
python3 src/taxonomy_mapper.py

# Step 3a only (uses most recent mapped data)
python3 src/report_generator.py
```

## Immediate next steps (after first run)

1. **Connect to a real broker.** Copy `config.example.yaml` → `config.yaml`, fill in SEMP credentials, and run `python3 run_pipeline.py --config config.yaml --vpn ACME_PROD`.
2. **Validate taxonomy parsing.** Open the generated Excel report → *Topic Catalogue* sheet. Check that business objects and event types are parsed correctly. If topics deviate from the expected convention, adjust the `taxonomy.levels` mapping in `config.yaml`.
3. **Extend taxonomy rules.** Open `output/taxonomy_rules.yaml` and manually annotate any domains, business objects, or applications that were not auto-detected (wildcards, legacy topics, non-standard naming).
4. **Review the Event Flows matrix.** The *Event Flows* sheet shows which applications consume which business objects. Share with the integration team to identify gaps and validate ownership.
5. **Provision an Event Portal API token** and run the Phase 2 import script (planned) to push the catalogue into Event Portal Designer/Catalog.

## What is extracted (Step 1)

From the Solace SEMP v2 API (`/SEMP/v2/config` and `/SEMP/v2/monitor`):

- **Message VPNs** — configuration and enabled state
- **Queues** — access type, owner, spool config, all topic subscriptions
- **Client profiles** — connection limits and permissions
- **ACL profiles** — publish/subscribe access control rules
- **Client usernames** — application identities with profile assignments
- **Topic endpoints** — durable topic subscribers (if present)
- **Connected clients** (monitor API) — runtime view of active connections
- **Queue stats** (monitor API) — message counts, spool usage, bind counts

## Topic taxonomy (Step 2)

ACME topics follow (or approximate) this structure:

```
<prefix> / <environment> / <domain> / <businessObject> / <eventType> / <version>
```

Example: `acme/prod/sales/Order/Created/v1`

The mapper auto-derives rules from observed topics and stores them in `output/taxonomy_rules.yaml`. Manually extend this file to handle exceptions, legacy topics, or wildcard subscriptions that cannot be auto-classified.

### Taxonomy level configuration

Edit `config.yaml` to match ACME's actual convention if it differs:

```yaml
taxonomy:
  separator: "/"
  levels:
    0: "prefix"
    1: "environment"
    2: "domain"
    3: "businessObject"
    4: "eventType"
    5: "version"
```

## Excel report (Step 3a)

The generated `.xlsx` workbook contains seven sheets:

| Sheet | Content |
|-------|---------|
| Summary | High-level counts and extraction metadata |
| Message VPNs | VPN configuration |
| Queues | All queues with stats and subscriptions |
| Topic Catalogue | All unique topics parsed by taxonomy level |
| Applications | Client usernames with queues, consumed BOs, domains |
| Business Objects | BO catalogue with event types and versions |
| Event Flows | App × Business Object matrix (C = consumes, P = produces) |

> **Note on Event Flows:** The consumer side (queue subscriptions) is fully populated. The producer side requires ACL publish exception data or Event Portal, and will be completed in Phase 2.

## Step 3b — Event Portal integration

The Solace Event Portal provides a searchable catalogue and Design-First workflow for event-driven assets. Populating it from the mapped data follows this sequence:

1. Create an **Application Domain** per domain (sales, finance, warehouse, ...)
2. Create **Event** objects for each businessObject/eventType combination
3. Create **Application** objects per client username, linked to consumed events
4. Publish **JSON Schema stubs** to the schema registry (enriched in Phase 2)

**Tooling options:**
- [Event Portal REST API](https://api.solace.dev/eventPortal/reference) — batch import scripts
- [Event Portal MCP Server](https://github.com/SolaceLabs/solace-platform-mcp) — conversational asset creation with Claude

A dedicated `src/event_portal_importer.py` is planned for Phase 2.

## Step 3c — Collibra integration (optional)

> **Collibra is entirely optional.** The pipeline (extract → map → report) runs without any Collibra credentials. If `collibra` keys are absent from `config.yaml` the pipeline is unaffected. The integration is a Phase 2 deliverable for organisations that already have Collibra licensed.

For organisations using Collibra as an enterprise metadata catalogue, the `mapped_data_*.json` output maps to Collibra assets as follows:

| Solace concept | Collibra asset type |
|----------------|---------------------|
| Message VPN | System |
| Business Object | Business Term / Data Entity |
| Event (Order Created) | Data Set / Event |
| Topic string | Data Attribute |
| Application (client username) | Application |
| Queue | Data Flow |

A `src/collibra_exporter.py` script (Phase 2 deliverable) will use the Collibra REST API to create and maintain these assets, enabling data lineage, GDPR/DPIA support, and cross-platform discoverability alongside database and API assets.

## Governance roadmap

See `docs/ACME_Event_Governance_Roadmap_v1.0.docx` for the full four-phase roadmap covering:

- Current state assessment and gap analysis
- Target architecture (Event Portal as system of record)
- Phase 1: Discovery & baseline catalogue (this project)
- Phase 2: Schema registry & publisher discovery (agentic)
- Phase 3: Naming standards & governance enforcement
- Phase 4: Design-First & full automation
- AI tooling strategy (Claude + Event Portal MCP + Collibra)
- Decision points and immediate next steps

## Known limitations (Phase 1)

- **Publisher detection** is not available from SEMP alone. Who publishes to a topic requires ACL publish exception inspection or runtime message tracing (Phase 2).
- **Schemas** are not stored in the broker and must be sourced from application teams or inferred from sample payloads (Phase 2).
- **Wildcard ACL subscriptions** may mask specific topics in use.
- **Topics deviating from the naming convention** are flagged in the taxonomy output but may require manual classification.

## References

| Resource | URL |
|----------|-----|
| SEMP v2 API Reference (AEM) | https://help.pubsub.em.services.cloud.sap/Admin/SEMP/SEMP-API-Ref.htm |
| Solace Cloud REST API v2 | https://api.solace.dev/cloud/reference |
| Event Portal REST API | https://api.solace.dev/eventPortal/reference |
| Event Portal MCP Server | https://github.com/SolaceLabs/solace-platform-mcp |
| SAP AEM MCP Servers | https://github.com/marianfoo/sap-ai-mcp-servers |
| AsyncAPI Specification | https://www.asyncapi.com/docs/reference/specification/latest |
| Solace Developer Portal | https://solace.dev |
