/*
 * mock_ea.js — minimal but strict in-memory mock of the Sparx EA 17.x automation
 * object model, sufficient for the APIs used by EAM-AI-ADMBw-Script-Maker templates.
 *
 * Scope: Repository (Models, Get*ByID, SQLQuery, BatchAppend, EnableUIUpdates),
 * Package/Packages, Element/Elements, Connector/Connectors, TaggedValues, Diagrams.
 * Semantics are modelled on the documented EA behaviour:
 *  - AddNew adds an in-memory object, Update() persists it (false + GetLastError on failure)
 *  - Refresh() on the parent collection
 *  - IDs/GUIDs are assigned when AddNew is called (EA assigns on Update, but templates
 *    only read them after Update; this mock is deliberately generous there and records it)
 *  - SQLQuery returns EA-style XML <EADATA><Dataset><Data><Row><C>n</C></Row>...
 */
'use strict';

var ELEMENT_TYPES = ['Class', 'Object', 'Activity', 'Requirement', 'Package', 'Text', 'UseCase',
    'Component', 'Node', 'Part', 'Slot', 'Action', 'StateMachine', 'DataType', 'Port', 'Interface',
    'Actor', 'Artifact', 'Enumeration', 'Signal', 'Constraint', 'Note'];
var CONNECTOR_TYPES = ['Association', 'Dependency', 'Generalization', 'Abstraction', 'Realisation',
    'Realization', 'InformationFlow', 'Aggregation', 'Composition', 'ControlFlow', 'ObjectFlow',
    'Message', 'Signal', 'Connector', 'NoteLink', 'PackageImport', 'Usage'];

function guid() {
    var hex = '0123456789abcdef';
    var s = '';
    for (var i = 0; i < 32; i++) { s += hex.charAt(Math.floor(Math.random() * 16)); }
    // EA GUIDs are uppercase brace-less in the DB, but property returns {GUID}
    return '{' + s.substr(0, 8) + '-' + s.substr(8, 4) + '-' + s.substr(12, 4) + '-' +
        s.substr(16, 4) + '-' + s.substr(20, 12) + '}';
}

function lastErr(store, msg) { store.lastError = msg; return false; }

/* ---------- Tagged values ---------- */
function TaggedValue(name, value) {
    this.Name = name;
    this.Value = value;
    this._persisted = false;
}
TaggedValue.prototype.Update = function () { this._persisted = true; return true; };

function TaggedValueCollection(owner) {
    this._owner = owner;
    this._items = [];
}
Object.defineProperty(TaggedValueCollection.prototype, 'Count', {
    get: function () { return this._items.length; }
});
TaggedValueCollection.prototype.GetAt = function (i) {
    if (i < 0 || i >= this._items.length) { throw new Error('TaggedValues.GetAt out of range: ' + i); }
    return this._items[i];
};
TaggedValueCollection.prototype.AddNew = function (name, value) {
    var tv = new TaggedValue(name, value === undefined ? '' : value);
    this._items.push(tv);
    return tv;
};
TaggedValueCollection.prototype.Refresh = function () { return true; };
TaggedValueCollection.prototype.DeleteAt = function (i) { this._items.splice(i, 1); return true; };

/* ---------- Connectors ---------- */
function Connector(repo, clientId, type) {
    this._repo = repo;
    this.ClientID = clientId;
    this.SupplierID = 0;
    this.Type = type;
    this.Name = '';
    this.Stereotype = '';
    this.StereotypeEx = '';
    this.ConnectorID = repo._nextConnectorId++;
    this.ConnectorGUID = guid();
    this._persisted = false;
}
Connector.prototype.Update = function () {
    var repo = this._repo;
    if (repo.failConnectorUpdate) {
        repo.lastError = 'Mock: connector update rejected (' + this.Type + ')';
        return false;
    }
    if (!CONNECTOR_TYPES.some(function (t) { return t.toLowerCase() === String(this.Type).toLowerCase(); }, this)) {
        repo.lastError = 'Mock: invalid connector type "' + this.Type + '"';
        return false;
    }
    if (!repo._elementsById[this.ClientID]) {
        repo.lastError = 'Mock: client element ' + this.ClientID + ' does not exist';
        return false;
    }
    if (!this.SupplierID || !repo._elementsById[this.SupplierID]) {
        repo.lastError = 'Mock: supplier element ' + this.SupplierID + ' does not exist';
        return false;
    }
    this._persisted = true;
    return true;
};
Connector.prototype.GetLastError = function () { return this._repo.lastError || ''; };
Object.defineProperty(Connector.prototype, 'StereotypeEx', {
    get: function () { return this._stereotypeEx || ''; },
    set: function (v) {
        this._stereotypeEx = v === null || v === undefined ? '' : String(v);
        this.Stereotype = this._stereotypeEx.split(',')[0].replace(/^\s+|\s+$/g, '');
    }
});

function ConnectorCollection(owner) {
    this._owner = owner;       // Element
    this._repo = owner._repo;
    this._items = [];
}
Object.defineProperty(ConnectorCollection.prototype, 'Count', {
    get: function () { return this._items.length; }
});
ConnectorCollection.prototype.GetAt = function (i) {
    if (i < 0 || i >= this._items.length) { throw new Error('Connectors.GetAt out of range: ' + i); }
    return this._items[i];
};
ConnectorCollection.prototype.AddNew = function (name, type) {
    var c = new Connector(this._repo, this._owner.ElementID, type);
    c.Name = name || '';
    this._items.push(c);
    this._repo._connectors.push(c);
    return c;
};
ConnectorCollection.prototype.Refresh = function () { return true; };
ConnectorCollection.prototype.DeleteAt = function (i) { this._items.splice(i, 1); return true; };

/* ---------- Elements ---------- */
function Element(repo, name, type, packageId) {
    this._repo = repo;
    this.Name = name;
    this.Type = type;
    this.Stereotype = '';
    this._stereotypeEx = '';
    this.Alias = '';
    this.Notes = '';
    this.ElementID = repo._nextElementId++;
    this.ElementGUID = guid();
    this.PackageID = packageId || 0;
    this.TaggedValues = new TaggedValueCollection(this);
    this.Connectors = new ConnectorCollection(this);
    this._persisted = false;
}
Object.defineProperty(Element.prototype, 'StereotypeEx', {
    get: function () { return this._stereotypeEx; },
    set: function (v) {
        this._stereotypeEx = v === null || v === undefined ? '' : String(v);
        // EA mirrors the first stereotype into Stereotype
        this.Stereotype = this._stereotypeEx.split(',')[0].replace(/^\s+|\s+$/g, '');
    }
});
Element.prototype.Update = function () {
    var repo = this._repo;
    if (typeof this.Name !== 'string' || this.Name.length === 0) {
        repo.lastError = 'Mock: element name is required';
        return false;
    }
    if (!ELEMENT_TYPES.some(function (t) { return t.toLowerCase() === String(this.Type).toLowerCase(); }, this)) {
        repo.lastError = 'Mock: invalid element type "' + this.Type + '"';
        return false;
    }
    if (repo.failElementUpdates && repo.failElementUpdates.indexOf(this.Name) !== -1) {
        repo.lastError = 'Mock: element update rejected for ' + this.Name;
        return false;
    }
    if (repo.failAllElementUpdates) {
        repo.lastError = 'Mock: element update rejected (global)';
        return false;
    }
    this._persisted = true;
    repo._elementsById[this.ElementID] = this;
    return true;
};
Element.prototype.GetLastError = function () { return this._repo.lastError || ''; };
Element.prototype.Refresh = function () { return true; };

function ElementCollection(pkg) {
    this._pkg = pkg;
    this._repo = pkg._repo;
    this._items = [];
}
Object.defineProperty(ElementCollection.prototype, 'Count', {
    get: function () { return this._items.length; }
});
ElementCollection.prototype.GetAt = function (i) {
    if (i < 0 || i >= this._items.length) { throw new Error('Elements.GetAt out of range: ' + i); }
    return this._items[i];
};
ElementCollection.prototype.AddNew = function (name, type) {
    var el = new Element(this._repo, name, type, this._pkg.PackageID);
    this._items.push(el);
    return el;
};
ElementCollection.prototype.Refresh = function () { return true; };
ElementCollection.prototype.DeleteAt = function (i) { this._items.splice(i, 1); return true; };

/* ---------- Diagrams ---------- */
function Diagram(repo, name, type, pkgId) {
    this._repo = repo;
    this.Name = name;
    this.Type = type;
    this.DiagramID = repo._nextDiagramId++;
    this.DiagramGUID = guid();
    this.PackageID = pkgId;
    this.DiagramObjects = { Count: 0, AddNew: function () { throw new Error('not needed'); }, Refresh: function () {} };
    this._persisted = false;
}
Diagram.prototype.Update = function () { this._persisted = true; return true; };
Diagram.prototype.GetLastError = function () { return ''; };

function DiagramCollection(pkg) {
    this._pkg = pkg;
    this._repo = pkg._repo;
    this._items = [];
}
Object.defineProperty(DiagramCollection.prototype, 'Count', { get: function () { return this._items.length; } });
DiagramCollection.prototype.GetAt = function (i) { return this._items[i]; };
DiagramCollection.prototype.AddNew = function (name, type) {
    if (!type) { throw new Error('Mock: diagram type required'); }
    var d = new Diagram(this._repo, name, type, this._pkg.PackageID);
    this._items.push(d);
    this._repo._diagrams.push(d);
    return d;
};
DiagramCollection.prototype.Refresh = function () { return true; };

/* ---------- Packages ---------- */
function Package(repo, name, parentId, isModel) {
    this._repo = repo;
    this.Name = name;
    this.ParentID = parentId || 0;
    this.IsModel = !!isModel;
    this.PackageID = repo._nextPackageId++;
    this.PackageGUID = guid();
    this.Packages = new PackageCollection(this);
    this.Elements = new ElementCollection(this);
    this.Diagrams = new DiagramCollection(this);
    this.Element = new Element(repo, name, 'Package', this.PackageID);
    this.Element.ElementID = this.PackageID; // EA: package element shares the package ID
    this.Element.ElementGUID = this.PackageGUID;
    this.Element._isPackageElement = true;
    this._persisted = false;
}
Package.prototype.Update = function () {
    var repo = this._repo;
    if (typeof this.Name !== 'string' || !this.Name.length) {
        repo.lastError = 'Mock: package name is required';
        return false;
    }
    if (repo.failPackageUpdates && repo.failPackageUpdates.indexOf(this.Name) !== -1) {
        repo.lastError = 'Mock: package update rejected for ' + this.Name;
        return false;
    }
    this._persisted = true;
    repo._packagesById[this.PackageID] = this;
    return true;
};
Package.prototype.GetLastError = function () { return this._repo.lastError || ''; };

function PackageCollection(owner) {
    this._owner = owner;
    this._repo = owner._repo;
    this._items = [];
}
Object.defineProperty(PackageCollection.prototype, 'Count', { get: function () { return this._items.length; } });
PackageCollection.prototype.GetAt = function (i) {
    if (i < 0 || i >= this._items.length) { throw new Error('Packages.GetAt out of range: ' + i); }
    return this._items[i];
};
PackageCollection.prototype.AddNew = function (name, type) {
    var parentId = this._owner.PackageID;
    var p = new Package(this._repo, name, parentId, false);
    this._items.push(p);
    return p;
};
PackageCollection.prototype.Refresh = function () { return true; };
PackageCollection.prototype.DeleteAt = function (i) { this._items.splice(i, 1); return true; };

/* ---------- Repository ---------- */
function Repository(opts) {
    opts = opts || {};
    this._nextElementId = 100;
    this._nextPackageId = 10;
    this._nextConnectorId = 500;
    this._nextDiagramId = 1;
    this._elementsById = {};
    this._packagesById = {};
    this._connectors = [];
    this._diagrams = [];
    this._models = [];
    this.output = [];
    this.lastError = '';
    this.batchLog = [];
    this.failElementUpdates = opts.failElementUpdates || null;
    this.failAllElementUpdates = !!opts.failAllElementUpdates;
    this.failPackageUpdates = opts.failPackageUpdates || null;
    this.failConnectorUpdate = !!opts.failConnectorUpdate;
    this.sqlErrorMode = !!opts.sqlErrorMode;
    this.sqlTrace = [];
    this._batchAppend = false;
    this._uiUpdates = true;

    var self = this;
    this.Models = new PackageCollection({
        _repo: this,
        IsModel: true,
        get PackageID() { return 0; }
    });
    // Models.AddNew must create a top-level model package
    var models = this.Models;
    models.AddNew = function (name) {
        var p = new Package(self, name, 0, true);
        models._items.push(p);
        self._models.push(p);
        return p;
    };
}
Object.defineProperty(Repository.prototype, 'BatchAppend', {
    get: function () { return this._batchAppend; },
    set: function (v) { this._batchAppend = !!v; this.batchLog.push(!!v); }
});
Object.defineProperty(Repository.prototype, 'EnableUIUpdates', {
    get: function () { return this._uiUpdates; },
    set: function (v) { this._uiUpdates = !!v; }
});

Repository.prototype.GetPackageByID = function (id) {
    return this._packagesById[id] || null;
};
Repository.prototype.GetElementByID = function (id) {
    return this._elementsById[id] || null;
};
Repository.prototype.GetLastError = function () { return this.lastError || ''; };
Repository.prototype.GetConnectorByID = function (id) {
    for (var i = 0; i < this._connectors.length; i++) {
        if (this._connectors[i].ConnectorID === id) return this._connectors[i];
    }
    return null;
};
Repository.prototype.GetPackageByGuid = function (g) {
    for (var k in this._packagesById) {
        if (this._packagesById[k].PackageGUID === g) return this._packagesById[k];
    }
    return null;
};

Repository.prototype.allElements = function () {
    var out = [];
    for (var k in this._elementsById) {
        if (this._elementsById.hasOwnProperty(k) && this._elementsById[k]._persisted) out.push(this._elementsById[k]);
    }
    return out;
};
Repository.prototype.persistedConnectors = function () {
    return this._connectors.filter(function (c) { return c._persisted; });
};

Repository.prototype.sql = function (sql) {
    this.sqlTrace.push(sql);
    return sql.replace(/\s+/g, ' ').trim();
};

function xmlRow(alias, value) {
    return '<?xml version="1.0" encoding="UTF-8"?>\n' +
        '<EADATA version="1.0" exporter="Enterprise Architect">\n' +
        '<Dataset name="Query1" columnCount="1"><Data><Row><' + alias + '>' + value +
        '</' + alias + '></Row></Data></Dataset>\n</EADATA>';
}

Repository.prototype.SQLQuery = function (sql) {
    var q = this.sql(sql);
    var self = this;
    if (this.sqlErrorMode) {
        // Simulates a DB error: EA returns no rows, not an exception.
        return '<?xml version="1.0" encoding="UTF-8"?>\n<EADATA version="1.0"><Dataset name="Query1"><Data></Data></Dataset></EADATA>';
    }

    var m = q.match(/FROM t_object WHERE Stereotype = '([^']*)'/i);
    if (m) {
        var stereo = m[1];
        var n = this.allElements().filter(function (e) {
            return !e._isPackageElement &&
                String(e.Stereotype).toLowerCase() === stereo.toLowerCase();
        }).length;
        return xmlRow('C', n);
    }
    m = q.match(/FROM t_connector WHERE Connector_Type = '([^']*)'/i);
    if (m) {
        var ct = m[1];
        var cn = this.persistedConnectors().filter(function (c) {
            return String(c.Type).toLowerCase() === ct.toLowerCase();
        }).length;
        return xmlRow('C', cn);
    }
    if (/Start_Object_ID NOT IN \(SELECT Object_ID FROM t_object\)/i.test(q)) {
        var ids = {};
        this.allElements().forEach(function (e) { ids[e.ElementID] = true; });
        var bad = this.persistedConnectors().filter(function (c) {
            return !ids[c.ClientID] || !ids[c.SupplierID];
        }).length;
        return xmlRow('C', bad);
    }
    if (/GROUP BY ea_guid/i.test(q) && /FROM t_connector/i.test(q)) {
        var seenC = {}, dupC = 0;
        this.persistedConnectors().forEach(function (c) {
            if (seenC[c.ConnectorGUID]) { dupC++; } else { seenC[c.ConnectorGUID] = true; }
        });
        return xmlRow('C', dupC);
    }
    if (/FROM t_connector/i.test(q) && /COUNT\(\*\)/i.test(q)) {
        return xmlRow('C', this.persistedConnectors().length);
    }
    if (/GROUP BY ea_guid/i.test(q)) {
        var seen = {}, dup = 0;
        this.allElements().forEach(function (e) {
            if (seen[e.ElementGUID]) { dup++; } else { seen[e.ElementGUID] = true; }
        });
        return xmlRow('C', dup);
    }
    if (/FROM t_diagram/i.test(q)) {
        return xmlRow('C', this._diagrams.filter(function (d) { return d._persisted; }).length);
    }
    if (/FROM t_object/i.test(q) && /COUNT\(\*\)/i.test(q)) {
        /* verify_model.js zählt nur Nicht-Paket-Objekte (Object_Type <> 'Package') */
        return xmlRow('C', this.allElements().filter(function (e) { return !e._isPackageElement; }).length);
    }
    // Unknown query: EA returns an error document; the template's parser yields 0.
    return '<?xml version="1.0" encoding="UTF-8"?>\n<EADATA version="1.0"><Dataset name="Query1">' +
        '<Error>Mock: unsupported SQL</Error></Dataset></EADATA>';
};

Repository.prototype.addDiagram = function (pkg, name, type) {
    return pkg.Diagrams.AddNew(name, type);
};

function Session(repo) { this._repo = repo; }
Session.prototype.Output = function (msg) { this._repo.output.push(String(msg)); };
Session.prototype.Prompt = function () { return 'resultNo'; };

function createRepository(opts) {
    var repo = new Repository(opts);
    return { Repository: repo, Session: new Session(repo), repo: repo };
}

module.exports = {
    createRepository: createRepository,
    ELEMENT_TYPES: ELEMENT_TYPES,
    CONNECTOR_TYPES: CONNECTOR_TYPES
};
