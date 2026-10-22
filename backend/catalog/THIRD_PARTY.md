# Third-party code in `backend/catalog`

Parts of this package are copied or adapted from MIT-licensed ComfyUI plugins.
Each is listed with the exact commit it was taken from, so it can be compared
or re-synced later.

| BlockFlow file | Source | Commit | How |
|---|---|---|---|
| `basemodel.py` | [EY4O/ComfyUI-Model-Librarian](https://github.com/EY4O/ComfyUI-Model-Librarian) `smf/basemodel.py` | `9b388aa` | Copied unchanged (attribution header added). Keep it unmodified; BlockFlow tweaks go in `vocab.py`. |
| `vocab.py` (`CIVITAI_BASE_MODELS`) | [Zellione/comfyui-tiny-model-manager](https://github.com/Zellione/comfyui-tiny-model-manager) `frontend/src/app/utils/base-models.ts` | `4438fb5` | List copied. |
| `civitai.py` (model search params) | [Zellione/comfyui-tiny-model-manager](https://github.com/Zellione/comfyui-tiny-model-manager) `py/services/providers/civitai_provider.py` | `4438fb5` | Adapted (curl_cffi, sync, BlockFlow item shape). |
| `civitai.py` (gallery images, prompt/LoRA extraction) | [fabwaseem/ComfyUI-Civitai-Gallery-Explorer](https://github.com/fabwaseem/ComfyUI-Civitai-Gallery-Explorer) `Civitai_Gallery_Explorer.py` | `b1aa47d` | Logic re-implemented (`withMeta`, prompt keys, LoRA resource rule). |
| `huggingface.py` | [Zellione/comfyui-tiny-model-manager](https://github.com/Zellione/comfyui-tiny-model-manager) `py/services/providers/huggingface_provider.py` | `4438fb5` | Adapted (curl_cffi, sync, no README rendering). |

## Licenses

### ComfyUI-Model-Librarian

```
MIT License

Copyright (c) 2026 EY4O

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### comfyui-tiny-model-manager

```
MIT License

Copyright (c) 2026 Zellione

(Same MIT terms as above.)
```

### ComfyUI-Civitai-Gallery-Explorer

```
MIT License

Copyright (c) 2025 Waseem Anjum

(Same MIT terms as above.)
```
