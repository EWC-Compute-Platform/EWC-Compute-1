# ADR-007 — Flexible Surrogate Tokenisation and `surrogate_compute_budget` as a Runtime Parameter

**Status:** Accepted
**Date:** April 2026
**Deciders:** Engineering World Company
**Relates to:** ADR-004 (ai_mode as explicit field), ADR-005 (PhysicsNeMo as AI physics framework)

---

## Context

EWC Compute's `surrogate` ai_mode (defined in ADR-004) was originally specified
as a single operating point: one trained PhysicsNeMo model, one accuracy level,
one compute cost per simulation domain. An engineer selecting `surrogate` mode
had no way to trade accuracy against speed at runtime — doing so required
training a separate model at a different resolution.

In March 2026, Polymathic AI published **Overtone** (Muk et al., 2026), a
framework that makes the patch size of patch-based transformer surrogates a
runtime parameter rather than a training constant. Two mechanisms — Convolutional
Stride Modulation (CSM) and Convolutional Kernel Modulation (CKM) — allow a
single trained model to serve multiple tokenisation scales at inference time.

The key results from the Overtone paper are:

- One Overtone-trained model, on the same compute budget as three fixed-patch
  models, matches or exceeds all three across their respective accuracy-speed
  operating points.
- Cyclic rollout schedules (alternating patch sizes across autoregressive steps,
  e.g. 4→8→16→4→8→16) reduce long-horizon rollout error by 30–40% by breaking
  the coherence of discretisation artefacts that accumulate at fixed spatial
  frequencies over many steps.
- Results hold consistently across 2D and 3D benchmarks spanning shear flow,
  Rayleigh-Bénard convection, active matter, and supernova dynamics.

Walrus (McCabe et al., 2025), from the same Polymathic AI group, incorporated
the Overtone approach at 1.3B parameter scale across 19 physical domains,
reducing one-step prediction error by 63.6% against the best prior specialised
models. Both papers are MIT licensed.

NVIDIA PhysicsNeMo is the expected production path for Overtone-style
architectures within EWC Compute's stack (ADR-005). The Overtone authors
confirmed CSM integration into Walrus at scale. The research-to-framework
pipeline (Polymathic AI → PhysicsNeMo → EWC Compute) is the established
pattern for AI physics improvements in this stack.

The consequence of Overtone for EWC Compute's `SimTemplate` schema is
concrete: the `surrogate` mode gains a meaningful runtime dial that was not
previously architecturally expressible. Without a schema field to capture it,
the decision would be made implicitly by the platform rather than explicitly
by the engineer — which violates the explicit-over-implicit principle
established in ADR-004.

Additionally, the ESSS/Ansys industrial simulation webinar (April 2026)
provided real-world validation of the surrogate mode value proposition:
the Ansys SimAI crane hook case demonstrated R² of 0.907–0.999 with less
than 1% stress difference from full Mechanical solve, in ~50 seconds versus
20 minutes on 4 CPU cores. This confirms that surrogate accuracy at multiple
fidelity levels is a decision engineers in the target market actively make
and value.

---

## Decision

**We extend the `SimTemplate` schema with a `surrogate_compute_budget` field,
active only when `ai_mode` is `surrogate`. We update `surrogate_router.py`
to pass this parameter through to the PhysicsNeMo inference call. We do not
implement Overtone tokenisation directly in Phase 2 — we define the schema
contract now so the field is in place when PhysicsNeMo exposes the capability.**

Specifically:

### 1. New field on `SimTemplate`

```python
class SurrogateComputeBudget(str, Enum):
    EXPLORATORY  = "exploratory"   # Large patch size → fast, coarse
    STANDARD     = "standard"      # Medium patch size → balanced (default)
    HIGH_FIDELITY = "high_fidelity" # Small patch size → slow, accurate

class SimTemplate(BaseModel):
    # ... existing fields ...
    ai_mode: AiMode
    surrogate_compute_budget: SurrogateComputeBudget = SurrogateComputeBudget.STANDARD
    # Field is active only when ai_mode == AiMode.SURROGATE.
    # Ignored (and not validated against) for generative and principled_solve modes.
```

### 2. Validation rule

`surrogate_compute_budget` is validated only when `ai_mode == "surrogate"`.
For `generative` and `principled_solve` modes the field is accepted but has
no effect. This avoids a breaking schema change and allows future modes to
adopt the field without migration.

```python
@model_validator(mode="after")
def validate_compute_budget(self) -> "SimTemplate":
    if self.ai_mode != AiMode.SURROGATE:
        # Silently coerce to STANDARD — budget is meaningless outside surrogate mode
        object.__setattr__(self, "surrogate_compute_budget",
                           SurrogateComputeBudget.STANDARD)
    return self
```

### 3. `surrogate_router.py` update

The router passes `surrogate_compute_budget` to the PhysicsNeMo inference
call as a configuration parameter. In Phase 2, before PhysicsNeMo exposes
Overtone-style tokenisation natively, the budget maps to existing
PhysicsNeMo model resolution settings (where available) or is logged and
ignored (where not yet supported). The field is never silently dropped.

```python
BUDGET_TO_PATCH_SIZE: dict[SurrogateComputeBudget, int] = {
    SurrogateComputeBudget.EXPLORATORY:   16,  # Large patch → fast, coarse
    SurrogateComputeBudget.STANDARD:       8,  # Medium patch → balanced
    SurrogateComputeBudget.HIGH_FIDELITY:  4,  # Small patch → accurate
}
```

### 4. What this ADR does NOT decide

- The exact Overtone architecture to be used in PhysicsNeMo training. That
  is a training configuration decision made in `nvidia_cae/physicsnemo/`
  when Phase 2–3 surrogate training begins.
- Whether to use cyclic rollout schedules (the 30–40% long-horizon error
  reduction result from the Overtone paper). That is a training-time choice.
- The specific patch size values above. These are initial estimates —
  actual values will be calibrated per domain during Phase 2–3 surrogate
  training and may differ by domain (CFD, FEM, thermal, EM).

---

## Consequences

### Positive

**Eliminates a hidden architectural decision.** Without this field, the
platform would always run surrogates at a fixed resolution and the engineer
would have no visibility into the accuracy-speed trade-off being made on
their behalf. Naming it as `surrogate_compute_budget` follows the same
explicit-over-implicit principle as `ai_mode` (ADR-004).

**Reduces Phase 3 training cost.** A single Overtone-capable PhysicsNeMo
model per domain serves all three budget levels. Without this decision,
Phase 3 would require three separate trained models per domain (one per
resolution), tripling training compute and versioning overhead.

**Positions EWC Compute ahead of the research curve.** The schema contract
is defined before PhysicsNeMo exposes the capability. When PhysicsNeMo
integrates Overtone (the trajectory is clear given CSM's incorporation into
Walrus), EWC Compute's implementation is a one-line change in
`surrogate_router.py`, not an architectural migration.

**Maps to real engineer decision-making.** The crane hook SimAI case from
ESSS confirms that engineers in the target market actively choose between
rapid design sweeps (fast, approximate) and pre-validation surrogates
(accurate, slower). `exploratory | standard | high_fidelity` maps cleanly
onto this decision vocabulary.

**Substack credibility.** The Overtone Research Intelligence post (EWC
Compute, April 2026) described this schema extension as the architectural
consequence of Overtone. This ADR closes the loop between the public
content and the codebase — the reasoning published on Substack is now
formally committed as an architectural decision.

### Negative / risks

**Schema field added before the underlying capability exists.** In Phase 2,
`surrogate_compute_budget` may be partially or fully ignored by PhysicsNeMo
depending on which resolution controls are exposed. Engineers using the
field before Phase 3 training completes will not see differentiated behaviour.
Mitigation: the API response for surrogate runs will include a
`compute_budget_applied: bool` field indicating whether the budget was
honoured or fell back to `STANDARD`.

**Patch size mapping is domain-dependent.** The values in
`BUDGET_TO_PATCH_SIZE` are initial estimates. CFD surrogates and FEM
surrogates may require different optimal patch sizes for the same budget
level. Mitigation: `surrogate_router.py` accepts domain-specific overrides
via a configuration dictionary populated during Phase 2–3 training.

**Dependency on Polymathic AI research trajectory.** If Overtone-style
tokenisation is not adopted into PhysicsNeMo, the `high_fidelity` and
`exploratory` budget levels reduce to labels with no implementation
backing. Mitigation: the Walrus integration at 1.3B scale confirms the
direction; the MIT licence means direct integration into PhysicsNeMo
training pipelines is feasible without a commercial dependency.

---

## Alternatives considered

### Keep surrogate mode as a single operating point

Rejected. The Overtone result makes single-point surrogate mode a missed
opportunity and the ESSS real-world data confirms the engineering demand.
Retrofitting the schema field later would require a migration of all
existing `SimTemplate` records.

### Use a numeric `surrogate_resolution` float field (0.0–1.0)

Rejected. A continuous float does not communicate the discrete nature of
patch size selection and gives engineers no vocabulary to discuss their
choice. `exploratory | standard | high_fidelity` maps to how engineers
already think about simulation fidelity trade-offs. The three-level
vocabulary also matches the three fidelity levels of the Digital Twin
Engine (geometric, behavioural, predictive), reinforcing a consistent
platform-wide framing of the accuracy-cost trade-off.

### Wait for PhysicsNeMo to expose Overtone natively before adding the field

Rejected. This violates the ADR-004 principle of explicit-over-implicit.
The decision exists whether or not the field exists — without the field,
the platform is silently making the choice for the engineer. The field
must exist before the capability so that engineers can form expectations
and so that the schema migration cost is zero at Phase 3.

---

## References

- Muk et al. (2026). *Overtone: Flexible Patch Modulation for Physics Transformers*.
  Polymathic AI. [github.com/payelmuk150/patch-modulator](https://github.com/payelmuk150/patch-modulator)
- McCabe et al. (2025). *Walrus: A Foundation Model for Diverse Physics Prediction*.
  Polymathic AI. [github.com/PolymathicAI/walrus](https://github.com/PolymathicAI/walrus)
- EWC Compute Research Intelligence No. 1 (2026). *The Physics Foundation Model
  Layer Is Forming — And It Changes How EWC Compute Thinks About Surrogates*.
  [engineeringworldcompany.substack.com](https://engineeringworldcompany.substack.com)
- ESSS/Ansys Industrial Simulation Webinar, April 2026. Crane hook SimAI case:
  R² 0.907–0.999, <1% stress difference, ~50s vs 20 min on 4 cores.
- ADR-004: `ai_mode` as an explicit schema field.
- ADR-005: PhysicsNeMo as AI physics framework.

---

*Engineering World Company · EWC Compute Platform*
*ADRs record the reasoning behind significant architectural decisions.
They are never deleted — superseded ADRs are marked as such.*
