# backend/scripts/seeds/

Scripts that create seed entities (logic_gates, agents, skills, actions) in
a fresh tenant database.

| Path | Purpose |
|------|---------|
| `default_entities/SeedAutonomousBI/` | Autonomous BI logic_gate + agents + skills. |
| `default_entities/SeedDocumentFactory/` | Document Factory logic_gate + actions for docx/pdf/pptx/xlsx/qa. |
| `deep_research/DeepResearchSetup/` | Deep-Research v2 seed (entities, triggers). |

Run any script directly with the backend virtualenv activated; each
sub-folder has its own entry point (`create_*` or `trigger_*`).
