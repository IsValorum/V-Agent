# tools/ — GGUF helpers

| File | Used for |
|---|---|
| `gguf_reader.py` | Reads a GGUF file's header (architecture, context length, chat template) without loading weights. |
| `strata_tokenizer.py` | Tokenizer used to check a model's chat template when it is imported. |

Both come from the Strata project (MIT, see [LICENSE.Strata](../LICENSE.Strata)).
