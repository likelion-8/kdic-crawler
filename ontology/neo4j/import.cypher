// Generated canonical ontology import. Copy CSV files into Neo4j's import directory.
CREATE CONSTRAINT ontology_node_id IF NOT EXISTS FOR (n:OntologyNode) REQUIRE n.id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///nodes-actor.csv' AS row
MERGE (n:OntologyNode:Actor {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'Actor', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-businessdomain.csv' AS row
MERGE (n:OntologyNode:BusinessDomain {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'BusinessDomain', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-concept.csv' AS row
MERGE (n:OntologyNode:Concept {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'Concept', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-contactpoint.csv' AS row
MERGE (n:OntologyNode:ContactPoint {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'ContactPoint', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-document.csv' AS row
MERGE (n:OntologyNode:Document {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'Document', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-eligibilityrule.csv' AS row
MERGE (n:OntologyNode:EligibilityRule {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'EligibilityRule', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-fact.csv' AS row
MERGE (n:OntologyNode:Fact {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'Fact', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-monetaryrule.csv' AS row
MERGE (n:OntologyNode:MonetaryRule {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'MonetaryRule', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-officiallabel.csv' AS row
MERGE (n:OntologyNode:OfficialLabel {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'OfficialLabel', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-procedure.csv' AS row
MERGE (n:OntologyNode:Procedure {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'Procedure', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-requireddocument.csv' AS row
MERGE (n:OntologyNode:RequiredDocument {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'RequiredDocument', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///nodes-service.csv' AS row
MERGE (n:OntologyNode:Service {id: row.id})
SET n.label = row.label, n.status = row.status, n.node_type = 'Service', n.properties_json = row.properties_json;

LOAD CSV WITH HEADERS FROM 'file:///edges-asserts_about.csv' AS row
MATCH (a:OntologyNode {id: row.start_id}), (b:OntologyNode {id: row.end_id})
MERGE (a)-[r:ASSERTS_ABOUT]->(b)
SET r.evidence_page_id = CASE WHEN row.evidence_page_id = '' THEN null ELSE row.evidence_page_id END;

LOAD CSV WITH HEADERS FROM 'file:///edges-belongs_to_domain.csv' AS row
MATCH (a:OntologyNode {id: row.start_id}), (b:OntologyNode {id: row.end_id})
MERGE (a)-[r:BELONGS_TO_DOMAIN]->(b)
SET r.evidence_page_id = CASE WHEN row.evidence_page_id = '' THEN null ELSE row.evidence_page_id END;

LOAD CSV WITH HEADERS FROM 'file:///edges-belongs_to_service.csv' AS row
MATCH (a:OntologyNode {id: row.start_id}), (b:OntologyNode {id: row.end_id})
MERGE (a)-[r:BELONGS_TO_SERVICE]->(b)
SET r.evidence_page_id = CASE WHEN row.evidence_page_id = '' THEN null ELSE row.evidence_page_id END;

LOAD CSV WITH HEADERS FROM 'file:///edges-documents_service.csv' AS row
MATCH (a:OntologyNode {id: row.start_id}), (b:OntologyNode {id: row.end_id})
MERGE (a)-[r:DOCUMENTS_SERVICE]->(b)
SET r.evidence_page_id = CASE WHEN row.evidence_page_id = '' THEN null ELSE row.evidence_page_id END;

LOAD CSV WITH HEADERS FROM 'file:///edges-evidence_for.csv' AS row
MATCH (a:OntologyNode {id: row.start_id}), (b:OntologyNode {id: row.end_id})
MERGE (a)-[r:EVIDENCE_FOR]->(b)
SET r.evidence_page_id = CASE WHEN row.evidence_page_id = '' THEN null ELSE row.evidence_page_id END;

LOAD CSV WITH HEADERS FROM 'file:///edges-label_for.csv' AS row
MATCH (a:OntologyNode {id: row.start_id}), (b:OntologyNode {id: row.end_id})
MERGE (a)-[r:LABEL_FOR]->(b)
SET r.evidence_page_id = CASE WHEN row.evidence_page_id = '' THEN null ELSE row.evidence_page_id END;
