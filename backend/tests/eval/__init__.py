"""Offline A/B eval harness for kernel changes (Phase 12 `07` §5).

Replays a fixed corpus through two named configs and reports goal-hit /
cost-per-success / false-pass / latency deltas *with* significance, so a
prompt/mode/model change is "+6pp goal-hit at −9% cost, p<0.05" rather than a
hunch. The pure metric/delta math lives in :mod:`metrics`; the corpus replay in
:mod:`runner`; named configs in :mod:`config`.
"""
