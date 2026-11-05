"""bpmn -- BPMN 2.0 fuer die ADMBw-Prozessmodellierung (L4).

Die Bibliothek ist bewusst schlank und ohne Fremdpakete lauffaehig:

* ``modell``    -- Datenmodell (Prozess, Pool, Lane, Knoten, Fluss, Datenobjekt)
* ``bpmn_xml``  -- Lesen und Schreiben von BPMN 2.0 XML inklusive Diagrammteil
* ``layout``    -- deterministische Anordnung ohne Zufall und ohne Zeitstempel
* ``exporte``   -- SVG und PNG aus dem Modell
* ``admbw``     -- Abbildung auf ADMBw-Stereotype und Pruefung nach L4-MK
* ``extraktion`` -- regelbasierte Prozess-Extraktion aus deutschem Fliesstext
* ``ki``        -- optionaler, standardmaessig ausgeschalteter KI-Adapter
* ``qea_bpmn``  -- Bruecke zum .qea-Writer

Die Regelgrundlage steht in ``knowledge/bpmn/prozess-regeln.json``; erzeugt
wird sie von ``scripts/build_bpmn_regeln.py`` aus MDG, Leitfaden und
Stereotypeliste. Kein Stereotyp wird hier von Hand erfunden.
"""

from __future__ import annotations

__all__ = ["modell", "bpmn_xml", "layout", "exporte", "admbw", "extraktion", "ki", "qea_bpmn"]

__version__ = "3.4.0"
