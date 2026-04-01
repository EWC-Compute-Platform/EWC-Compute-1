"""
EWC Compute — DigitalTwin Pydantic models.

A DigitalTwin is the central engineering object. All SimTemplate runs,
KPI Dashboard data, and Physical AI Assistant actions reference a twin.

Three fidelity levels reflect the NVIDIA CAE workflow:
  geometric    — shape, dimensions, interference checking (Phase 0 active)
  behavioural  — physics parameterisation + Sim Bridge coupling (Phase 2)
  predictive   — PhysicsNeMo surrogate generating real-time predictions (Phase 3)

The USD stage path records where the OpenUSD representation lives.
Phase 0: local .usda file. Phase 3: Omniverse Nucleus path (omniverse://...).

Collections:
  digital_twins — one document per twin
"""
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from beanie import Document, Indexed
from pydantic import BaseModel, Field

from app.models.project import SimulationDomain


# ── Enums ─────────────────────────────────────────────────────────────────

class FidelityLevel(StrEnum):
    """
    Twin fidelity determines which operations are permitted.

    geometric    — geometry only: shape, mesh, interference checking.
                   USD stage is written but no physics schema populated.
                   Safe to visualise and export; cannot be simulated.

    behavioural  — geometry + physics parameterisation: material properties,
                   boundary conditions, load cases. Connected to Sim Bridge
                   for validation runs. Required for principled_solve mode.

    predictive   — behavioural twin + trained PhysicsNeMo surrogate.
                   Returns physics field predictions (stress, pressure, temperature)
                   in seconds without invoking the full solver.
                   Active from Phase 3.
    """
    GEOMETRIC   = "geometric"
    BEHAVIOURAL = "behavioural"
    PREDICTIVE  = "predictive"


class AiMode(StrEnum):
    """
    AI mode for simulation template runs referencing this twin.
    Stored on the twin as the default; overridable per SimTemplate run.

    generative       — PhysicsNeMo cWGAN-GP: broad design space exploration.
                       Returns candidate configurations ranked by estimated performance.
                       Active from Phase 2.

    surrogate        — PhysicsNeMo PINN / AB-UPT: real-time physics predictions.
                       CAD-native, no meshing required, hard physics constraints.
                       Active from Phase 3.

    principled_solve — Full-fidelity solver via Sim Bridge.
                       CUDA-X routed: cuDSS (FEM/EDA) or AmgX (CFD/EM).
                       Active from Phase 2.
    """
    GENERATIVE       = "generative"
    SURROGATE        = "surrogate"
    PRINCIPLED_SOLVE = "principled_solve"


class GeometryFormat(StrEnum):
    """Source geometry format uploaded by the engineer."""
    STEP = "step"
    IGES = "iges"
    DXF  = "dxf"
    STL  = "stl"    # Import only; STL is also an export target
    USDZ = "usdz"   # Direct USD import


# ── Sub-models ────────────────────────────────────────────────────────────

class MaterialProperties(BaseModel):
    """
    Physics material properties for behavioural / predictive fidelity.
    All values in SI units unless noted.
    """
    material_name: str
    density_kg_m3: float | None = None          # kg/m³
    youngs_modulus_pa: float | None = None       # Pa
    poissons_ratio: float | None = None          # dimensionless
    thermal_conductivity_w_mk: float | None = None   # W/(m·K)
    specific_heat_j_kgk: float | None = None     # J/(kg·K)
    yield_strength_pa: float | None = None       # Pa
    custom_properties: dict[str, float] = Field(
        default_factory=dict,
        description="Domain-specific properties not covered by standard fields.",
    )


class BoundaryCondition(BaseModel):
    """
    A single boundary condition applied to a named surface or volume.
    Stored as a list on the twin; validated against the solver schema at dispatch.
    """
    name: str                        # e.g. "inlet", "fixed_wall", "symmetry_plane"
    bc_type: str                     # e.g. "velocity_inlet", "pressure_outlet", "fixed"
    value: float | list[float] | None = None
    units: str | None = None
    surface_tag: str | None = None   # Named surface in the USD geometry


class TwinGeometrySummary(BaseModel):
    """
    Lightweight geometry metadata stored on the twin document.
    Full geometry lives in the USD stage; this enables filtering without loading USD.
    """
    format: GeometryFormat
    vertex_count: int | None = None
    face_count: int | None = None
    bounding_box_mm: list[float] | None = None   # [xmin, ymin, zmin, xmax, ymax, zmax]
    usd_stage_path: str                          # Local .usda path (Phase 0) or
                                                 # omniverse://... path (Phase 3)


# ── Request / Response models ─────────────────────────────────────────────

class DigitalTwinCreate(BaseModel):
    """POST /projects/{project_id}/twins request body."""
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=1000)] = ""
    domain: SimulationDomain
    fidelity_level: FidelityLevel = FidelityLevel.GEOMETRIC
    default_ai_mode: AiMode = AiMode.PRINCIPLED_SOLVE
    geometry_format: GeometryFormat = GeometryFormat.STEP
    tags: list[str] = Field(default_factory=list)


class DigitalTwinUpdate(BaseModel):
    """PATCH /twins/{id} — partial update."""
    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    description: Annotated[str, Field(max_length=1000)] | None = None
    fidelity_level: FidelityLevel | None = None
    default_ai_mode: AiMode | None = None
    material_properties: MaterialProperties | None = None
    boundary_conditions: list[BoundaryCondition] | None = None
    tags: list[str] | None = None


class DigitalTwinPublic(BaseModel):
    """Twin representation returned in API responses."""
    id: str
    project_id: str
    name: str
    description: str
    domain: SimulationDomain
    fidelity_level: FidelityLevel
    default_ai_mode: AiMode
    geometry: TwinGeometrySummary | None
    material_properties: MaterialProperties | None
    boundary_conditions: list[BoundaryCondition]
    tags: list[str]
    sim_run_count: int
    created_at: datetime
    updated_at: datetime


class DigitalTwinSummary(BaseModel):
    """Compact representation for project twin lists."""
    id: str
    name: str
    domain: SimulationDomain
    fidelity_level: FidelityLevel
    sim_run_count: int
    updated_at: datetime


# ── Database document ─────────────────────────────────────────────────────

class DigitalTwin(Document):
    """
    MongoDB document. Stored in the 'digital_twins' collection.

    Every twin belongs to exactly one project.
    Access control: queries MUST filter by project_id.
    The project's owner_id / org_id provides the user-level access check.

    usd_stage_path: set at creation when the USD exporter writes the stage.
      Phase 0: local path, e.g. /data/twins/{twin_id}.usda
      Phase 3: Nucleus path, e.g. omniverse://localhost/Projects/{pid}/twins/{twin_id}.usdz
    """
    project_id: Annotated[str, Indexed()]
    name: str
    description: str = ""
    domain: SimulationDomain
    fidelity_level: FidelityLevel = FidelityLevel.GEOMETRIC
    default_ai_mode: AiMode = AiMode.PRINCIPLED_SOLVE

    # Geometry
    geometry_format: GeometryFormat = GeometryFormat.STEP
    usd_stage_path: str | None = None     # Set after USD export succeeds
    geometry_summary: TwinGeometrySummary | None = None

    # Physics parameterisation — populated at BEHAVIOURAL fidelity
    material_properties: MaterialProperties | None = None
    boundary_conditions: list[BoundaryCondition] = Field(default_factory=list)

    # Metadata
    tags: list[str] = Field(default_factory=list)
    sim_run_count: int = 0               # Denormalised; incremented per SimRun

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "digital_twins"
        indexes = [
            "project_id",
            [("project_id", 1), ("domain", 1)],        # Filter twins by domain
            [("project_id", 1), ("fidelity_level", 1)], # Filter by fidelity
        ]

    def to_public(self) -> DigitalTwinPublic:
        return DigitalTwinPublic(
            id=str(self.id),
            project_id=self.project_id,
            name=self.name,
            description=self.description,
            domain=self.domain,
            fidelity_level=self.fidelity_level,
            default_ai_mode=self.default_ai_mode,
            geometry=self.geometry_summary,
            material_properties=self.material_properties,
            boundary_conditions=self.boundary_conditions,
            tags=self.tags,
            sim_run_count=self.sim_run_count,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def to_summary(self) -> DigitalTwinSummary:
        return DigitalTwinSummary(
            id=str(self.id),
            name=self.name,
            domain=self.domain,
            fidelity_level=self.fidelity_level,
            sim_run_count=self.sim_run_count,
            updated_at=self.updated_at,
        )

    def can_simulate(self) -> bool:
        """
        True if the twin has the minimum required fields for a Sim Bridge dispatch.
        A geometric twin cannot be simulated — material properties and boundary
        conditions are required for behavioural fidelity.
        """
        return (
            self.fidelity_level in (FidelityLevel.BEHAVIOURAL, FidelityLevel.PREDICTIVE)
            and self.material_properties is not None
            and len(self.boundary_conditions) > 0
            and self.usd_stage_path is not None
        )
