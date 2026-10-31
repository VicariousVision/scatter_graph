"""Prompt templates: legal-domain extraction prompts and the grounded answer prompt."""

from neo4j_graphrag.generation import RagTemplate
from neo4j_graphrag.generation.prompts import ERExtractionTemplate, SchemaExtractionTemplate

# Labels the application itself uses. Entities must never take them, or they would be
# confused with documents, chunks or chat history.
RESERVED_LABELS = {"Document", "Chunk", "Session", "Message"}

NO_ANSWER = "I can't find that in the uploaded documents."

_LEGAL_SCHEMA_PREAMBLE = """
You are designing the graph schema for a LEGAL knowledge graph. The input is a sample of a
legal document (for example a contract, agreement, court judgment, statute, regulation,
policy, deed or legal correspondence). Other legal documents will be added to the same graph.

Legal-domain guidance:
- Prefer general, reusable legal node types when the text supports them, for example:
  Party, Person, Organization, GovernmentBody, Court, Judge, Agreement, Clause,
  DefinedTerm, Obligation, Right, Payment, Jurisdiction, Statute, Regulation, Case,
  Asset, Event.
- Model dates, monetary amounts, durations, addresses and reference numbers as
  properties of a node or relationship, not as node types.
- Every node type MUST include a "name" property of type STRING.
- Never use the labels Document, Chunk, Session or Message. Use Agreement or a more
  specific label for legal instruments instead of Document.
- Keep the schema compact: at most 12 node types and 15 relationship types.
- If the "Examples" section lists types that already exist in the knowledge graph,
  reuse those exact labels whenever they fit, and only add new types for concepts
  they do not cover.
"""


class LegalSchemaExtractionTemplate(SchemaExtractionTemplate):
    """The library's schema-extraction prompt with legal-domain guidance in front."""

    DEFAULT_TEMPLATE = _LEGAL_SCHEMA_PREAMBLE + SchemaExtractionTemplate.DEFAULT_TEMPLATE


class LegalERExtractionTemplate(ERExtractionTemplate):
    """Entity and relationship extraction prompt tuned for legal text."""

    DEFAULT_TEMPLATE = """
You are an expert legal analyst extracting information from a legal document to build a
knowledge graph.

Extract the entities (nodes) and specify their type from the input text.
Also extract the relationships between these nodes.

Legal extraction rules:
- Look for parties (people, companies, government bodies), courts and judges, agreements
  and other legal instruments, clauses and sections, defined terms, obligations, rights,
  payments, deadlines, jurisdictions and governing law, statutes, regulations and cases.
- Give each entity its canonical full name, e.g. "Acme Holdings Limited" rather than
  "Acme" or "the Company". If the text defines a role (e.g. "the Supplier") and says who
  it is, use the named party.
- Name clauses and sections by number and heading, e.g. "Clause 12.1 Limitation of Liability".
- Record dates, amounts, durations and percentages exactly as written, as properties.
- Extract only what the text states. Do not infer or invent facts.
- Every node must have a "name" property.

Return result as JSON using the following format:
{{"nodes": [ {{"id": "0", "label": "Party", "properties": {{"name": "Acme Holdings Limited"}} }}],
"relationships": [{{"type": "PARTY_TO", "start_node_id": "0", "end_node_id": "1", "properties": {{"role": "Supplier"}} }}] }}

Use only the following node and relationship types (if provided):
{schema}

Assign a unique ID (string) to each node, and reuse it to define relationships.
Do respect the source and target node types for relationship and
the relationship direction.

Make sure you adhere to the following rules to produce valid JSON objects:
- Do not return any additional information other than the JSON in it.
- Omit any backticks around the JSON - simply output the JSON on its own.
- The JSON object must not wrapped into a list - it is its own JSON object.
- Property names must be enclosed in double quotes

Examples:
{examples}

Input text:

{text}
"""


LEGAL_SYSTEM_INSTRUCTIONS = f"""You are a legal document assistant. You answer questions using a knowledge graph built from documents the user uploaded.

Rules you must always follow:
1. Answer ONLY from the "Context" section of the latest message. It contains excerpts from the uploaded documents and facts from the knowledge graph.
2. Never use outside knowledge, including general legal knowledge, statutes, case law or assumptions, even if you know the answer.
3. If the context does not contain the answer, reply exactly: "{NO_ANSWER}" You may then briefly say what related information the context does contain.
4. Cite the source file name in square brackets after each claim, for example [lease-agreement.pdf].
5. Quote the exact wording when precise language matters (definitions, obligations, deadlines, amounts).
6. Use earlier messages only to understand what the user is referring to. Every fact in your answer must be supported by the current context.
7. You do not give legal advice. If asked what the user should do, say you cannot give legal advice and summarise only what the documents say.
8. Be concise. Use short paragraphs or bullet points."""


LEGAL_RAG_TEMPLATE = RagTemplate(
    template="""Context:
{context}

{examples}

Question:
{query_text}

Answer using only the context above, and cite the source file names in square brackets:
""",
    expected_inputs=["context", "query_text", "examples"],
    system_instructions=LEGAL_SYSTEM_INSTRUCTIONS,
)
