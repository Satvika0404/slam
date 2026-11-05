# Usage report

Final full-dataset run that produced `output.csv` (518 cases, 32.5 s).

## Decision path (what produced `output.csv`)

- Model provider: none (rules and OCR only)
- Model calls: 0 (OCR resolved every screenshot, rules classified every request)
- Input / output tokens: 0 / 0, cost $0.00

## Optional model cross-check (does not change `output.csv`)

- Model provider: `groq`, model `qwen/qwen3.8-27b`
- Model calls: 76 attempted, 76 succeeded, 0 failed (ceiling 120)
- Input / output tokens: 48477 / 5852 (total 54329; average 715 per call, 104.9 per request over 518 requests)
- Estimated cost: not estimated (no per-token price was supplied: free tier or unpriced), so no dollar figure is claimed
- Per-model totals: `qwen/qwen3.8-27b` only, the figures above
- Per key (labels only, never values):
  - key#1: cooling, 25 ok / 38 tried, 13 rate-limited, 13457 in / 1782 out tokens
  - key#2: cooling, 10 ok / 18 tried, 8 rate-limited, 10081 in / 1761 out tokens
  - key#3: active, 22 ok / 32 tried, 10 rate-limited, 12818 in / 939 out tokens
  - key#4: active, 19 ok / 31 tried, 12 rate-limited, 12121 in / 1370 out tokens
