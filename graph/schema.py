"""
Neo4j schema for Sherlock forensic graph.

Node labels:   Case | Person | Organization | Location | Evidence
Relationship types:
  (Person)     -[:SUSPECT_IN]->    (Case)
  (Person)     -[:WITNESS_IN]->    (Case)
  (Person)     -[:VICTIM_IN]->     (Case)
  (Person)     -[:OFFICER_IN]->    (Case)
  (Person)     -[:ASSOCIATED_WITH]->(Person)    {strength: float}
  (Person)     -[:LOCATED_AT]->    (Location)   {context: str}
  (Person)     -[:MEMBER_OF]->     (Organization)
  (Organization)-[:INVOLVED_IN]-> (Case)
  (Evidence)   -[:LINKED_TO]->     (Case)
  (Evidence)   -[:IMPLICATES]->    (Person)

All nodes carry case_id so a single DB serves many cases.
Phase 7: VSS video ER uses the same schema — Person/Location nodes are merged by name+case_id.
"""

CONSTRAINTS = [
    "CREATE CONSTRAINT case_id IF NOT EXISTS FOR (c:Case) REQUIRE c.case_id IS UNIQUE",
    "CREATE INDEX person_case IF NOT EXISTS FOR (p:Person) ON (p.name, p.case_id)",
    "CREATE INDEX location_case IF NOT EXISTS FOR (l:Location) ON (l.name, l.case_id)",
    "CREATE INDEX org_case IF NOT EXISTS FOR (o:Organization) ON (o.name, o.case_id)",
    "CREATE INDEX evidence_case IF NOT EXISTS FOR (e:Evidence) ON (e.id, e.case_id)",
]

EXTRACTION_SYSTEM_PROMPT = """You are a forensic entity extractor. Given a document from a criminal case,
extract all named entities and relationships. Be precise — only extract what is explicitly stated.

Return a JSON object with this exact structure:
{
  "entities": [
    {"label": "Person", "name": "...", "role": "suspect|witness|victim|officer|unknown", "nationality": "...", "age": null},
    {"label": "Organization", "name": "...", "org_type": "gang|company|government|other"},
    {"label": "Location", "name": "...", "district": "..."},
    {"label": "Evidence", "id": "...", "description": "...", "evidence_type": "physical|digital|testimonial|forensic"}
  ],
  "relations": [
    {"from_label": "Person", "from_name": "...", "relation": "SUSPECT_IN|WITNESS_IN|VICTIM_IN|ASSOCIATED_WITH|LOCATED_AT|MEMBER_OF|IMPLICATES", "to_label": "Case|Person|Location|Organization|Evidence", "to_name": "...", "context": "..."}
  ]
}

Rules:
- Use null for unknown fields, not empty strings
- Deduplicate entities by name (same person = one entry)
- Only include relations explicitly supported by the text"""
