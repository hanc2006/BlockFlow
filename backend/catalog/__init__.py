"""Model catalog: search CivitAI and Hugging Face, return one normalized shape.

Modules:
  basemodel    base-model family detection (vendored, see THIRD_PARTY.md)
  vocab        CivitAI base-model vocabulary, families, media, types, folders
  civitai      CivitAI provider (models, versions, gallery images)
  huggingface  Hugging Face provider (repos, files)
  service      dispatch + TTL cache used by backend/catalog_routes.py

Every model item has the same keys regardless of source:
  source, id, name, type, type_raw, base_model, family, media, tags, nsfw,
  creator, stats{downloads, likes}, thumbnail, url, trigger_words,
  versions[{id, name, base_model, family, trigger_words, files[...], download}]
`download` is BlockFlow's preset model entry {source, url, dest, sha256}, so it
can go straight through preset_resolver / the existing download flow.
"""
