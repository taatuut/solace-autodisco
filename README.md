# Solace AutoDisco

Automated discovery and cataloguing of events, topics, and applications for SAP Advanced Event Mesh (AEM) / Solace Cloud Platform brokers.

> **Disclaimer:** this repo is not officially supported by Solace. All efforts have been made to make this code working and safe, but usage is at your own responsibility.

## What this project does

An event-driven integration landscape (SAP AEM, powered by Solace) carries business events between applications such as ERP, WMS, e-commerce, finance, and logistics systems. Without automation, there is no reliable overview of what is flowing, how it is defined, or which applications produce and consume which events.

This project automates that discovery and produces three outputs:

| Output | File | Description |
|--------|------|-------------|
| Raw broker data | `output/raw/semp_extract_*.json` | Full SEMP v2 extraction |
| Mapped & enriched data | `output/reports/mapped_data_*.json` | Topics parsed, applications identified, business objects catalogued |
| Excel report (Step 3) | `output/reports/solace_autodisco_report_*.xlsx` | Multi-sheet workbook for stakeholder review — 7 sheets, or 10 if manual taxonomy overrides are in use |

## Project structure

```
solace-autodisco/                       # committed to Git
├── src/
│   ├── __init__.py
│   ├── semp_extractor.py               # Step 1: Extract from SEMP v2 API
│   ├── taxonomy_mapper.py              # Step 2: Map topics to your taxonomy
│   └── report_generator.py            # Step 3: Generate Excel report
├── tests/
│   └── test_pipeline.py                # Regression tests (see Tests below)
├── .github/
│   └── workflows/
│       └── test.yml                    # CI: runs pytest on push/PR
├── run_pipeline.py                     # Single-command full pipeline
├── config.example.yaml                 # Connection config template
├── requirements.txt
├── requirements-dev.txt                # Adds pytest, for running tests/
├── pytest.ini
├── .gitignore
├── LICENSE
└── output/
    └── taxonomy_rules.example.yaml    # Taxonomy rules template

# created locally from templates, gitignored
├── config.yaml                         # Your SEMP credentials
├── .venv/                              # Python virtual environment
└── output/
    ├── raw/                            # Raw SEMP JSON extracts
    ├── reports/                        # Mapped JSON + Excel reports
    └── taxonomy_rules.yaml             # Auto-derived snapshot + persisted manual overrides
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

# Step 3 only (uses most recent mapped data)
python3 src/report_generator.py
```

`report_generator.py` also accepts `--mock` on its own, running extract → map → report as a single command without going through `run_pipeline.py`:

```bash
python3 src/report_generator.py --mock
```

## Immediate next steps (after first live run)

1. **Validate taxonomy parsing.** Open the generated Excel report → *Topic Catalogue* sheet. Check that business objects and event types are parsed correctly. If the parsed columns look wrong, follow the [taxonomy tuning guide](#tuning-the-taxonomy-to-your-actual-topic-structure) below.
2. **Review the taxonomy snapshot and add overrides where needed.** Open `output/taxonomy_rules.yaml` to see what environments, domains, business objects, and event types were auto-detected. If something wasn't classified correctly, fix systematic issues by adjusting `taxonomy.levels` in `config.yaml`; for individual exceptions (wildcards, legacy topics), add entries under the `manual` keys instead — see [Manual taxonomy overrides](#manual-taxonomy-overrides).
3. **Review the Event Flows matrix.** The *Event Flows* sheet shows which applications consume which business objects. Share with the integration team to identify gaps and validate ownership.
4. **Provision an Event Portal API token** and run the Phase 2 import script (planned) to push the catalogue into Event Portal Designer/Catalog.

## Step 1 — What is extracted

From the Solace SEMP v2 API (`/SEMP/v2/config` and `/SEMP/v2/monitor`):

- **Message VPNs** — configuration and enabled state
- **Queues** — access type, owner, spool config, all topic subscriptions
- **Client profiles** — connection limits and permissions
- **ACL profiles** — publish/subscribe access control rules
- **Client usernames** — application identities with profile assignments
- **Topic endpoints** — durable topic subscribers (if present)
- **Connected clients** (monitor API) — runtime view of active connections
- **Queue stats** (monitor API) — message counts, spool usage, bind counts

For interactive, ad-hoc exploration of a broker's live topic traffic — complementary to this pipeline's automated, point-in-time SEMP extraction — see the [Solace Topic Explorer](https://explorer.solace.dev/), a browser-based tool for browsing topics and message flows on a Solace broker in real time.

## Step 2 — Topic taxonomy

Every organisation names its topics differently. The taxonomy is what maps *your* raw topic strings into the business-meaningful facets (domain, business object, event type, ...) used throughout the Topic Catalogue, Business Objects, and Event Flows sheets in the Excel report — without it, the pipeline only has opaque topic strings to work with.

Topics typically follow (or approximate) this structure:

```
<prefix> / <environment> / <domain> / <businessObject> / <eventType> / <version>
```

Example: `acme/prod/sales/Order/Created/v1`

**Configuration** — the position-to-label mapping that controls parsing lives in `config.yaml` under `taxonomy.levels` (see [Taxonomy level configuration](#taxonomy-level-configuration) below). This is the only file that affects how topics are classified; adjust it to match your organisation's actual convention.

**Usage** — on every run, the mapper parses each observed topic against the current `taxonomy.levels` and writes a summary of what it found (observed environments, domains, business objects, event types) to `output/taxonomy_rules.yaml`. Those observation lists are regenerated from scratch every run — they're a snapshot for review, not a persistent config. Topics that don't fit the convention, or wildcard subscriptions, show up with empty or `None` parsed columns in the report; fix systematic misclassifications by adjusting `taxonomy.levels` in `config.yaml`. For individual exceptions that `taxonomy.levels` can't fix, see [Manual taxonomy overrides](#manual-taxonomy-overrides) below.

### Manual taxonomy overrides

Some topics can't be classified correctly from parsing alone — non-standard legacy topics, wildcard subscriptions, or one-off exceptions to the convention. `output/taxonomy_rules.yaml` has two override maps for exactly this, each split into an `auto` and a `manual` sub-key:

```yaml
topicPatternToBusinessObject:
  auto: {}      # regenerated every run from parsed topics — don't edit
  manual: {}    # your corrections — persist across runs, win over auto
domainToApplicationGroup:
  auto: {}      # not currently auto-derived — always empty
  manual: {}    # your groupings — persist across runs
```

Only edit the `manual` sub-keys — anything under `auto` is overwritten on the next run. Manual entries are read back on every subsequent run and always take precedence over the auto-derived value for the same key.

- **`topicPatternToBusinessObject.manual`** — maps a topic prefix (the first 4 segments, up to the businessObject level) to a business object, overriding whatever parsing produced for that prefix.
  ```yaml
  topicPatternToBusinessObject:
    manual:
      acme/prod/legacy: Order
  ```
- **`domainToApplicationGroup.manual`** — declares that an application belongs to a domain, in addition to whatever the pipeline inferred from its subscriptions (it adds to the parsed set, it doesn't replace it).
  ```yaml
  domainToApplicationGroup:
    manual:
      sales: [app_order_svc, app_erp_sap]
  ```

Rerun the pipeline to apply them:

```bash
python3 run_pipeline.py --config config.yaml
```

When manual overrides are present, the Excel report gains three additional sheets — **Applications (Overrides)**, **Business Objects (Overrides)**, and **Event Flows (Overrides)** — showing the same data recomputed with your overrides applied, alongside the unmodified parsed-only sheets so you can compare both. The Summary sheet reports whether any overrides were applied.

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

## Step 3 — Excel report

The generated `.xlsx` workbook always contains these seven sheets, built from parsed data only:

| Sheet | Content |
|-------|---------|
| Summary | High-level counts and extraction metadata, including whether manual overrides were applied |
| Message VPNs | VPN configuration |
| Queues | All queues with stats and subscriptions |
| Topic Catalogue | All unique topics parsed by taxonomy level |
| Applications | Client usernames with queues, consumed BOs, domains |
| Business Objects | BO catalogue with event types and versions |
| Event Flows | App × Business Object matrix (C = consumes, P = produces) |

> **Note on Event Flows:** The consumer side (queue subscriptions) is fully populated. The producer side requires ACL publish exception data or Event Portal, and will be completed in Phase 2.

If `output/taxonomy_rules.yaml` has any [manual taxonomy overrides](#manual-taxonomy-overrides), three more sheets are added with the same content recomputed with those overrides applied:

| Sheet | Content |
|-------|---------|
| Applications (Overrides) | Same as Applications, with both override maps applied: `topicPatternToBusinessObject.manual` reclassifications (affects Business Objects Consumed) and `domainToApplicationGroup.manual` groupings (affects Domains) |
| Business Objects (Overrides) | Same as Business Objects, with `topicPatternToBusinessObject.manual` reclassifications applied |
| Event Flows (Overrides) | Same matrix, built from the two sheets above |

The parsed-only sheets are never replaced — the overridden sheets sit alongside them so you can compare both.

## Step 4 — Event Portal integration

The Solace Event Portal provides a searchable catalogue and Design-First workflow for event-driven assets. Populating it from the mapped data follows this sequence:

1. Create an **Application Domain** per domain (sales, finance, warehouse, ...)
2. Create **Event** objects for each businessObject/eventType combination
3. Create **Application** objects per client username, linked to consumed events
4. Publish **JSON Schema stubs** to the schema registry (enriched in Phase 2)

**Tooling options:**
- [Event Portal REST API](https://api.solace.dev/eventPortal/reference) — batch import scripts
- [Event Portal MCP Server](https://github.com/SolaceLabs/solace-platform-mcp) — conversational asset creation with Claude

A dedicated `src/event_portal_importer.py` is planned for Phase 2.

## Step 5 — Collibra integration (optional)

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
- **Topics deviating from the naming convention** are flagged in the taxonomy output; use [manual taxonomy overrides](#manual-taxonomy-overrides) for exceptions that `taxonomy.levels` can't handle systematically.
- **Only the `manual` sub-keys in `output/taxonomy_rules.yaml` persist across runs.** The observation lists and each override field's `auto` sub-key are regenerated from scratch every run; edits there are lost on the next run.
- **`topicPatternToBusinessObject.manual` keys on the first 4 topic segments** (up to the businessObject level). Topics with fewer segments than that can't be matched by this override.
- **`domainToApplicationGroup.manual` adds to, not replaces, an application's inferred domains** — it's a union with the parsed set, not a correction of it.

## Tests

Automated regression tests live in `tests/` and cover two things:

- **Clean-state regression** of every documented command — `run_pipeline.py --mock`, each step run individually, `report_generator.py --mock` standalone, and live-mode invocation from the `cp`'d templates — run against a fresh copy of the repo's runtime files with no `config.yaml` or `taxonomy_rules.yaml` present, matching what a first-time user actually experiences.
- **Manual taxonomy overrides** — that entries under the `manual` keys in `output/taxonomy_rules.yaml` survive regeneration across runs, get merged with the freshly auto-derived data, and produce the three `(Overrides)` sheets in the Excel report with correctly recomputed values.

Tests run the actual CLI entry points as subprocesses against an isolated temporary copy of the project — never against your real `output/` directory or `config.yaml`, and never against a live broker (everything uses `--mock`).

```bash
python3 -m pip install -r requirements-dev.txt
pytest
```

### Continuous Integration

`.github/workflows/test.yml` runs on every push and pull request against `main`: it installs `requirements-dev.txt`, runs a `py_compile` sanity check on `run_pipeline.py` and each `src/` script, then runs the full `pytest` suite. It needs no secrets or a live broker — everything uses `--mock`, same as running the tests locally.

## References

| Resource | URL |
|----------|-----|
| SEMP v2 API Reference (AEM) | https://help.pubsub.em.services.cloud.sap/Admin/SEMP/SEMP-API-Ref.htm |
| Solace Topic Explorer | https://explorer.solace.dev/ |
| Solace Cloud REST API v2 | https://api.solace.dev/cloud/reference |
| Event Portal REST API | https://api.solace.dev/eventPortal/reference |
| Event Portal MCP Server | https://github.com/SolaceLabs/solace-platform-mcp |
| SAP AEM MCP Servers | https://github.com/marianfoo/sap-ai-mcp-servers |
| AsyncAPI Specification | https://www.asyncapi.com/docs/reference/specification/latest |
| Solace Developer Portal | https://solace.dev |
