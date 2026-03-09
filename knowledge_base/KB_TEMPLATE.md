# KB Chunking Template — Jaded Rose

## A) Chunk Output Format (mandatory)

Every chunk must be formatted exactly like this:

```
KB_ID: <unique_id>
TYPE: <brand|support|legal|policy|product|faq|reference>
TITLE: <short human title>
TAGS: <comma-separated keywords for retrieval>
SOURCE: <original document filename>
VERSION: <YYYY-MM-DD>
PARENT_ID: <kb_id of parent chunk, or "none">
TEXT:
<verbatim source text for this chunk>
--- KB_CHUNK_END ---
```

### Field Rules

| Field       | Required | Description |
|-------------|----------|-------------|
| `KB_ID`     | Yes      | Unique, lowercase snake_case. Prefixed with `jadedrose_`. Stable across re-ingests. |
| `TYPE`      | Yes      | One of: `brand`, `support`, `legal`, `policy`, `product`, `faq`, `reference`. |
| `TITLE`     | Yes      | Short human-readable label for the chunk (used in retrieval logs). |
| `TAGS`      | Yes      | Comma-separated lowercase keywords to boost retrieval when user query doesn't match chunk text exactly. |
| `SOURCE`    | Yes      | Original document filename (e.g. `faq.md`, `returns_policy.md`). Tracks provenance for updates. |
| `VERSION`   | Yes      | Date the source content was last verified/updated (`YYYY-MM-DD`). |
| `PARENT_ID` | Yes      | KB_ID of the parent chunk if this is a sub-chunk (e.g. `_part_2`), otherwise `none`. |
| `TEXT`      | Yes      | Verbatim source text. No summarising, no additions. |

---

## B) Chunking Instructions

Paste this into the AI that converts raw docs into chunks:

```
You are a KB chunking engine.

Goal: Convert the provided document into multiple Pinecone-ready chunks using
the required format.

Hard constraints:
1) Do NOT add new information. Do NOT use external sources.
2) Preserve 100% of the provided content. No summarising, no deletion.
3) Split the document into many chunks using semantic boundaries (headings/sections).
4) Target chunk length: 300-1,200 words per chunk (preferred).
   - NEVER exceed ~1,800 words in a chunk.
   - If a section is longer, split into subchunks with suffixes (_part_1, _part_2)
     and set PARENT_ID on the sub-chunks to point to _part_1.
5) Use the exact delimiter line:  --- KB_CHUNK_END ---
6) Each chunk must include ALL fields: KB_ID, TYPE, TITLE, TAGS, SOURCE, VERSION, PARENT_ID, TEXT.
7) TEXT must contain only the source text (verbatim) for that chunk.
8) Do not include tables of contents or duplicate content unless it exists in the source.
9) Allow 1-2 sentences of overlap between adjacent chunks for context continuity.

Classification rules for TYPE:
- legal    : terms, refunds, returns, privacy, cookies, liability, shipping policy language
- policy   : chatbot rules, safety constraints, disclaimers, escalation, evidence vs claims
- product  : individual product details, catalogue entries, variants, pricing
- support  : how-to, contact, delivery steps, tracking steps, troubleshooting
- brand    : company story, overview, mission, awards, positioning
- faq      : Q&A formatted content
- reference: sources, citations, link lists, bibliography

KB_ID rules:
- Use lowercase snake_case.
- Prefix all KB_IDs with "jadedrose_".
- Make IDs descriptive and stable.
- If splitting a long section: "<id>_part_1", "<id>_part_2", etc.

TAGS rules:
- Lowercase, comma-separated.
- Include synonyms and related terms customers might search for.
- 3-8 tags per chunk.

VERSION rules:
- Use the date the source document was last updated.
- Format: YYYY-MM-DD.

Output only the final chunks in the required format. No commentary.
```

---

## C) TYPE Reference

| TYPE        | Use for                                                        | Example content                       |
|-------------|----------------------------------------------------------------|---------------------------------------|
| `brand`     | Company-level info, mission, story                             | "About Jaded Rose" section            |
| `product`   | Individual product details, catalogue                          | Shopify product descriptions          |
| `support`   | How-to guides, contact info, troubleshooting                   | "How to track my order"               |
| `legal`     | Returns policy, shipping terms, refund rules, privacy          | Returns eligibility, refund timelines |
| `policy`    | Chatbot behaviour rules, escalation triggers, safety           | "Never invent policy details"         |
| `faq`       | Q&A formatted content                                          | "Do you offer free shipping?" Q&A     |
| `reference` | Citations, link lists, external sources                        | Source bibliography                   |

---

## D) Example Chunk

```
KB_ID: jadedrose_returns_eligibility
TYPE: legal
TITLE: Returns eligibility requirements
TAGS: returns, eligibility, unworn, tags, condition, refund, exchange
SOURCE: returns_policy.md
VERSION: 2026-03-09
PARENT_ID: none
TEXT:
To be eligible for a return or exchange, items must be:
- Unworn and unwashed — tried on is fine, but the item must not have been worn out.
- In original condition — no marks, stains, odours, pet hair or damage.
- With all original tags attached — swing tags and hygiene stickers must still be in place.
- In original packaging — items should be returned in the bag or box they arrived in.
--- KB_CHUNK_END ---
```
