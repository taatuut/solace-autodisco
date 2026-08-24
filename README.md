# Solace AutoDisco

Automated discovery and cataloguing of events, topics, and applications on a SAP Advanced Event Mesh (AEM) / Solace platform.

## What this project does

An event-driven integration landscape (SAP AEM, powered by Solace) carries business events between applications such as ERP, WMS, e-commerce, finance, and logistics systems. Without automation, there is no reliable overview of what is flowing, how it is defined, or which applications produce and consume which events.

This project automates that discovery and produces three outputs:

| Output | File | Description |
|--------|------|-------------|
| Raw broker data | `output/raw/semp_extract_*.json` | Full SEMP v2 extraction |
| Mapped & enriched data | `output/reports/mapped_data_*.json` | Topics parsed, applications identified, business objects catalogued |
| Excel report (Step 3a) | `output/reports/solace_autodisco_report_*.xlsx` | Seven-sheet workbook for stakeholder review |

## Project structure

```
solace-autodisco/                       # committed to Git
├── src/
│   ├── __init__.py
│   ├── semp_extractor.py               # Step 1: Extract from SEMP v2 API
│   ├── taxonomy_mapper.py              # Step 2: Map topics to your taxonomy
│   └── report_generator.py            # Step 3a: Generate Excel report
├── run_pipeline.py                     # Single-command full pipeline
├── config.example.yaml                 # Connection config template
├── requirements.txt
└── output/
    └── taxonomy_rules.example.yaml    # Taxonomy rules template

# created locally from templates, gitignored
├── config.yaml                         # Your SEMP credentials
├── .venv/                              # Python virtual environment
└── output/
    ├── raw/                            # Raw SEMP JSON extracts
    ├── reports/                        # Mapped JSON + Excel reports
    └── taxonomy_rules.yaml             # Working taxonomy rules (company data)
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

No further setup required — the mock pipeline needs no `config.yaml` or taxonomy rules file; it uses built-in defaults.

```bash
python3 run_pipeline.py --mock
```

This runs the full extract → map → report pipeline with synthetic data and writes the Excel report to `output/reports/`.

### Live broker

Running against a real broker needs local config and taxonomy rules files, created once from the committed templates:

```bash
cp config.example.yaml config.yaml
cp output/taxonomy_rules.example.yaml output/taxonomy_rules.yaml
```

Fill in your SEMP credentials in `config.yaml`, then run:

```bash
python3 run_pipeline.py --config config.yaml
```

To target a specific VPN:

```bash
python3 run_pipeline.py --config config.yaml --vpn PROD
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

`report_generator.py` also accepts `--mock` on its own, running extract → map → report as a single command without going through `run_pipeline.py`:

```bash
python3 src/report_generator.py --mock
```

## Immediate next steps (after first live run)

1. **Validate taxonomy parsing.** Open the generated Excel report → *Topic Catalogue* sheet. Check that business objects and event types are parsed correctly. If the parsed columns look wrong, follow the [taxonomy tuning guide](#tuning-the-taxonomy-to-your-actual-topic-structure) below.
2. **Extend taxonomy rules.** Open `output/taxonomy_rules.yaml` and manually annotate any domains, business objects, or applications that were not auto-detected (wildcards, legacy topics, non-standard naming).
3. **Review the Event Flows matrix.** The *Event Flows* sheet shows which applications consume which business objects. Share with the integration team to identify gaps and validate ownership.
4. **Provision an Event Portal API token** and run the Phase 2 import script (planned) to push the catalogue into Event Portal Designer/Catalog.

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

Topics typically follow (or approximate) this structure:

```
<prefix> / <environment> / <domain> / <businessObject> / <eventType> / <version>
```

Example: `acme/prod/sales/Order/Created/v1`

The mapper auto-derives rules from observed topics and stores them in `output/taxonomy_rules.yaml`. Manually extend this file to handle exceptions, legacy topics, or wildcard subscriptions that cannot be auto-classified.

### Tuning the taxonomy to your actual topic structure

> **Note:** Taxonomy tuning only makes sense when running against a broker with your organisation's actual topic taxonomy. Runs against a demo or sandbox broker with non-standard topic naming will show mismatched or empty parsed columns — this is expected and not a problem. Perform the tuning steps below once connected to a broker that carries real integration traffic.

After that first run against a broker with your actual topic taxonomy, open the Excel report:

```
output/reports/solace_autodisco_report_<timestamp>.xlsx
```

Go to the **Topic Catalogue** sheet. The first column (`Topic (raw)`) lists every unique topic string found on the broker. The remaining columns show how the current `config.yaml` level definitions parsed each segment.

If the parsed columns look wrong — for example `environment` is showing application names, or `businessObject` is empty — the level definitions need to be adjusted.

**To derive the correct mapping with Claude Desktop:**

1. Copy a representative sample of 10–20 raw topic strings from the first column.
2. If any topics contain sensitive application or business data, sanitise them by replacing real names with placeholders (e.g. `acme/prod/erp/SalesOrder/Created/v1`), keeping the *structure* intact.
3. Paste the sample into Claude Desktop with this prompt:

   > "Here are topic strings from our Solace broker. Analyse the structure and suggest the correct `taxonomy.levels` mapping for `config.yaml`, where each level position maps to a semantic label such as prefix, environment, domain, businessObject, eventType, or version. Topic samples: [paste here]"

4. Claude will propose a `levels` block. Paste it into `config.yaml` under `taxonomy.levels` and rerun the pipeline:

   ```bash
   python3 run_pipeline.py --config config.yaml
   ```

5. Check the Topic Catalogue sheet again — the parsed columns should now reflect the correct semantic meaning for each segment.

### Taxonomy level configuration

Edit `config.yaml` to match your actual convention if it differs:

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
