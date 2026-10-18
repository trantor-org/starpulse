"""The JSON bodies the HTTP API sends and takes: one pydantic model per body, the page's types generated from them.

`starpulse._internal.server.server` builds every response through these models (`encoding.encode`), so a body that
drifts from its model is a 500 rather than a page that reads a missing field. Each model is also published as one
JSON Schema, `api.schema.json`, and `web/src/api/types.gen.ts` is generated from that; regenerate both with
`python -m starpulse.contracts.api` and `pnpm --dir starpulse/web run gen:types`.

`_base` holds the base model, `dto/` one module per family of bodies, `registry` the route tables and `schema`
the generated JSON Schema.
"""
