# Local presets

Presets in this folder are used when BlockFlow runs with
`BLOCKFLOW_USE_LOCAL_PRESETS` set:

| Value | Effect |
|-------|--------|
| `1` (or `true`, `yes`, `on`) | Local presets replace public-registry presets with the same `id`; new ids are added. Other presets still come from the registry, and local ones keep working if it is unreachable. |
| `only` | Only local presets; the public registry is not contacted. |
| unset | Public registry only (default). |

`BLOCKFLOW_LOCAL_PRESETS_DIR` points at another folder with the same layout,
e.g. on a persistent volume.

The format is the public registry's
([Hearmeman24/blockflow-presets](https://github.com/Hearmeman24/blockflow-presets)):
`manifest.json` lists the presets, and each preset has a `preset.json` plus
optional workflow files. `preset_url` and `workflows[].url` may be paths
relative to the file that contains them, or absolute https URLs. Only files
inside this folder are read.

After editing, use **Refresh** on the Presets page (the manifest is cached
for an hour).

## Included

- `ltx-2-3`: the registry preset with the 2x spatial upscaler switched from
  `ltx-2.3-spatial-upscaler-x2-1.0` (removed by Lightricks, now HTTP 404) to
  `...-x2-1.1`, in both the model list and the T2V workflow. The 1.1 file has
  no `sha256` here yet, so its download is not hash-checked.
- `wan22-svi-4pass`: the registry preset plus `upscale_models/2xLiveActionV1_SPAN_490000.pth`,
  the 2x upscaler its workflow loads but the registry preset does not download
  (source: the author's GitHub, as listed on OpenModelDB; license CC-BY-NC-SA-4.0,
  non-commercial). The workflow is a local copy (`workflow.json`) with one
  change: the high-noise lightning LoRA (node 883) is the Wan 2.2 Lightning
  Seko V1 `high_noise_model` at strength 1, paired with the low-noise one the
  preset already uses, instead of the Wan 2.1 lightx2v 480p LoRA at strength 4,
  whose `img_emb` keys do not exist in Wan 2.2 ("lora key not loaded"). Its
  download has no `sha256` here yet, so it is not hash-checked.
