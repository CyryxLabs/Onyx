# Capability delta — Phase 9 opportunity scoring V1

## Added behind one exact default-off flag

- Transparent deterministic opportunity scoring over twelve fixed dimensions
  with published per-dimension weights and explicit benefit/cost direction.
- Cost/risk inversion (competition, time to MVP/revenue, complexity,
  legal/platform risk score higher when their raw risk is lower).
- A `0..100` total via deterministic integer half-up rounding, a fixed band
  ladder (`watch`/`consider`/`pursue`/`priority`), a `low_confidence` flag and a
  batch rank (total descending, `opportunity_id` tie-break).
- A complete per-dimension breakdown so any total is recomputable from the
  returned record.

## Not added

- Live/primary source fetching or any provider call.
- Model-assisted or learned weighting; opportunity clustering.
- Any autonomous action on a score — a score can never trigger a trade.
- World Monitor connector — remains `BLOCKED_BY_LICENSE`.
- Any network, model call or persistence.
- Startup, V13, voice, dashboard or UI wiring; Phase 9 exit; full PRD completion.
