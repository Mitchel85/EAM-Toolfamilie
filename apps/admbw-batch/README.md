# ADMBw-Batch-Generator v2.1

![Status](https://img.shields.io/badge/Status-Active-success)
![Standard](https://img.shields.io/badge/Standard-MDG%202026.05-blue)
![Output](https://img.shields.io/badge/Output-JSON%20Batch-orange)
![Ziel](https://img.shields.io/badge/Ziel-ArAMIS%20WEB%20%7C%20Neo4j-purple)

KI-gestützter Agent zur Extraktion von ADMBw-konformen **Knoten und Kanten** aus Prosa-Dokumenten. Output ist ein **JSON-Batch**, der direkt in **ArAMIS WEB** (Neo4j) geladen werden kann.

> ⚠️ Erzeugt JSON-Batches zur manuellen Prüfung. Kein automatischer Import.

---

## 🎯 Was macht das Tool?

| Schritt | Beschreibung |
|---------|-------------|
| 1. Prosa-Analyse | Architekturrelevante Entitäten im Text identifizieren |
| 2. Stereotyp-Mapping | Jede Entität einem **konkreten** ADMBw-Stereotyp zuweisen (kein 🔒) |
| 3. Beziehungs-Extraktion | Kanten gemäß Topology-Regeln ableiten (client = Quelle, supplier = Ziel); abstrakte Endpunkte werden auf konkrete Subtypen aufgelöst |
| 4. JSON-Batch | Strukturierte Ausgabe mit `nodes[]` und `edges[]`, jede Kante KB-belegt |
| 5. Ladeanweisung | Exakter Cypher-Befehl für ArAMIS WEB / Neo4j |

---

## 📦 Output-Format

```json
{
  "metadata": { "generator": "ADMBw-Batch-Generator v2.1", "node_count": 6, "edge_count": 4 },
  "nodes": [
    { "id": "n1", "name": "...", "stereotype": "Capability", "metaclass": "Class", "labels": ["Capability"], "properties": {} }
  ],
  "edges": [
    { "id": "e1", "source_id": "n1", "target_id": "n2", "connector": "CapabilityDependency", "type": "CAPABILITY_DEPENDENCY", "metaclass": "Dependency", "properties": {} }
  ]
}
```

- `connector` (Pflicht): KB-Name des Connector-Stereotyps in **CamelCase**, exakt wie in `ADMBw-Knowledge-Topology.md` Spalte 1.
- `type` (optional): Neo4j-Relationstyp in **GROSSBUCHSTABEN** (UPPER_SNAKE_CASE). Fehlt er, lädt der Loader mit `connector`.
- `node_count`/`edge_count` sind die Längen der tatsächlich emittierten Arrays — nie geschätzt.
- Das verbindliche JSON-Schema liegt in [`examples/batch-schema.json`](examples/batch-schema.json); es ist identisch in `system_prompt.md` eingebettet.

→ Vollständiges Beispiel (jede Kante gegen die KB validiert): [`examples/output-example.json`](examples/output-example.json)

### Große Batches (Chunking)

Passt der Batch nicht in eine Antwort: mehrere **geschlossene, schema-valide** JSON-Dokumente (`metadata.chunk = "1/2", "2/2"`), je Chunk korrekte Zähler, IDs chunkweit eindeutig. **Niemals abgeschnittenes JSON** — bei drohendem Output-Limit lieber ein geschlossener Teil-Batch + Liste der fehlenden Entitäten + Ladeanweisung.

---

## 🚀 In ArAMIS WEB laden

ArAMIS WEB nutzt **Neo4j mit APOC**. Der JSON-Batch wird über die APOC-Prozeduren geladen:

### 1. JSON bereitstellen
```bash
# In Neo4j-Importverzeichnis kopieren (Podman)
podman cp batch.json <neo4j-container>:/var/lib/neo4j/import/
```

### 2. KNOTEN laden (Neo4j Browser / cypher-shell)
```cypher
CALL apoc.load.json("file:///import/batch.json") YIELD value
UNWIND value.nodes AS n
MERGE (node {id: n.id})
SET node.name = n.name,
    node.stereotype = n.stereotype,
    node.metaclass = n.metaclass
SET node += n.properties
WITH node, n
CALL apoc.create.addLabels(node, n.labels) YIELD node AS labeledNode
RETURN count(labeledNode) AS KnotenErstellt;
```

`SET node += n.properties` setzt **alle** im JSON gefüllten Properties dynamisch — kein hartkodiertes Aufzählen einzelner Properties.

### 3. KANTEN laden
```cypher
CALL apoc.load.json("file:///import/batch.json") YIELD value
UNWIND value.edges AS e
MATCH (src {id: e.source_id}), (tgt {id: e.target_id})
CALL apoc.merge.relationship(
  src, coalesce(e.type, e.connector),
  {connector: e.connector},
  {metaclass: e.metaclass},
  tgt
) YIELD rel
SET rel += e.properties
RETURN count(rel) AS BeziehungenErstellt;
```

### 4. Prüfen
```cypher
MATCH (n)-[e]-(m) RETURN n, e, m;
```

Bei Chunks (mehrere Dateien): Schritte 2 und 3 je Datei wiederholen.

---

## 📚 Wissensbasis

Vier MDG-generierte Knowledge-Dateien (in OpenWebUI als RAG-Wissen eingebunden), generiert vom [EAM-ADMBw-MDG-Parser](https://github.com/Mitchel85/EAM-ADMBw-MDG-Parser) aus der MDG 2026.05, plus eine kuratierte Connector-Übersicht:

| Datei | Inhalt |
|-------|--------|
| `ADMBw-Knowledge-Stereotypes.md` | **318 Katalog-Stereotype** (293 nutzbar · 44 abstrakt 🔒); Toolboxen/Artefakte sind nicht enthalten |
| `ADMBw-Knowledge-Viewpoints.md` | **52 Viewpoints** mit MDG-Beschreibung (keine erfundenen Properties) |
| `ADMBw-Knowledge-Topology.md` | **133 vollständige Kanten-Regeln** (Quelle/Ziel über client/source/end[0] bzw. supplier/target/end[1]) + 70 reine Rollen-Beschränkungen |
| `ADMBw-Knowledge-TagTypes.md` | **27 Property-Typen** (Tagged-Value-Definitionen) |
| `ADMBw-Knowledge-Connectors.md` | EA-Metatypen + Connector-Übersicht (kuratiert) |
| `ADMBw-Stereotypes.json` | Maschinenlesbarer Katalog mit `abstract` und `concreteDescendants` |
| `ADMBw-Aliases.json` | Schreibvarianten → kanonischer Name |

> **KB-Sync-Status (2026-10-19): aktuell.** Vier MDG-Dateien neu erzeugt aus `eam-mdg-parser` (`9470931`), identisch in Extractor und Batch; Tag-Typen und Hashes in `checks/deterministic-checks.json`.

---

## 🔧 Einrichtung (OpenWebUI)

1. **Modell anlegen** → Inhalt von `system_prompt.md` ins Feld **System Prompt**
2. **Knowledge** → Vier MDG-generierte `ADMBw-Knowledge-*.md`-Dateien, `ADMBw-Knowledge-Connectors.md` und beide JSON-Dateien hochladen und verknüpfen
3. Fertig. Erste Nachricht: Prosa-Dokument einfügen oder: *„Extrahiere ADMBw-Knoten und Kanten aus folgendem Text: …"*

---

## ✅ Deterministische Prüfung

`python3 checks/verify.py` prüft ohne LLM:

- KB-Statistiken (318/293/25/133/70/52) und KB-Hashes
- Schema in `system_prompt.md` == `examples/batch-schema.json`
- `examples/output-example.json` gegen JSON-Schema (jsonschema, Draft 2020-12) — 0 Fehler
- jede Beispiel-Kante gegen die Topologie-KB (exakter Match oder konkreter Subtyp eines erlaubten abstrakten Endpunkts) und jede Metaklasse gegen die Stereotype-KB
- `node_count`/`edge_count` == Array-Längen, IDs eindeutig, Referenzen gültig

---

## 📁 Repository

| Datei | Zweck |
|-------|-------|
| `system_prompt.md` | System-Prompt (Extraktionslogik + JSON-Schema + Chunking + Few-Shot) |
| `examples/batch-schema.json` | Verbindliches JSON-Schema (identisch im Prompt eingebettet) |
| `examples/output-example.json` | Beispiel-JSON-Batch (schema- und KB-valide) |
| `checks/verify.py` | Deterministische Prüfungen (ohne LLM) |
| `ADMBw-Knowledge-*.md` | Vier MDG-generierte Knowledge-Dateien + Connectors (s. o.) |

---

**Autor:** Michael Estel (mit KI-Agent)
