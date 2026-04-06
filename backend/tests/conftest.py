"""
EWC Compute — pytest fixtures for Phase 0 test suite.

Provides:
  app_client       — async FastAPI test client (no real DB/Redis)
  mongo_mock       — in-memory MongoDB via mongomock-motor
  redis_mock       — in-memory Redis via fakeredis
  test_user        — a registered, active User document
  test_user_token  — a valid JWT access token for test_user
  test_project     — a Project owned by test_user
  auth_headers     — {"Authorization": "Bearer <token>"} dict

Usage:
    async def test_health(app_client):
        response = await app_client.get("/health")
        assert response.status_code == 200

    async def test_create_project(app_client, auth_headers):
        response = await app_client.post(
            "/api/v1/projects",
            json={"name": "Test Project", "domain_tags": ["cfd"]},
            headers=auth_headers,
        )
        assert response.status_code == 201
"""
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from beanie import init_beanie
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.audit import AuditEvent
from app.models.project import Project
from app.models.sim_run import SimRun
from app.models.template import SimTemplate
from app.models.twin import DigitalTwin
from app.models.user import User, UserRole, SubscriptionTier


# ── Event loop ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Database mock ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def mongo_mock():
    """
    Replace MongoDB Atlas with an in-memory mongomock-motor client.
    Automatically used by all tests — no real Atlas connection required.
    Beanie is re-initialised for each test to ensure a clean document registry.
    """
    client = AsyncMongoMockClient()
    db = client[settings.MONGODB_DB_NAME]

    await init_beanie(
        database=db,
        document_models=[
            User,
            Project,
            DigitalTwin,
            SimTemplate,
            SimRun,
            AuditEvent,
        ],
    )

    # Patch the database module so the app uses the mock
    import app.core.database as db_module
    db_module._client = client
    db_module._db = db

    yield db

    # Drop all collections after each test for isolation
    for collection_name in await db.list_collection_names():
        await db.drop_collection(collection_name)


# ── Redis mock ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def redis_mock():
    """
    Replace Redis with an in-memory fakeredis instance.
    Automatically used by all tests — no real Redis required.
    """
    fake_redis = FakeRedis()

    import app.core.cache as cache_module
    cache_module._redis = fake_redis

    yield fake_redis

    await fake_redis.aclose()


# ── FastAPI test client ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def app_client(mongo_mock, redis_mock) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP test client for the FastAPI application.
    Uses ASGI transport — no real network calls.
    The lifespan is managed by LifespanManager (startup + shutdown hooks run).
    """
    # Import after fixtures are set up so mocks are in place
    from app.main import app

    # Override lifespan to skip real DB/Redis init (already mocked via autouse fixtures)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


# ── User fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_user() -> User:
    """A registered, active individual engineer user."""
    user = User(
        email="engineer@ewccompute.test",
        hashed_password=hash_password("Test1234!"),
        full_name="Test Engineer",
        role=UserRole.INDIVIDUAL,
        tier=SubscriptionTier.PROFESSIONAL,
    )
    await user.insert()
    return user


@pytest.fixture
def test_user_token(test_user: User) -> str:
    """Valid JWT access token for test_user."""
    return create_access_token(
        user_id=str(test_user.id),
        role=test_user.role,
        org_id=test_user.org_id,
    )


@pytest.fixture
def auth_headers(test_user_token: str) -> dict[str, str]:
    """Authorization header dict for authenticated requests."""
    return {"Authorization": f"Bearer {test_user_token}"}


# ── Admin user fixture ─────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin_user() -> User:
    """An admin-role user for testing RBAC-protected routes."""
    user = User(
        email="admin@ewccompute.test",
        hashed_password=hash_password("Admin1234!"),
        full_name="Test Admin",
        role=UserRole.ADMIN,
        tier=SubscriptionTier.ENTERPRISE,
    )
    await user.insert()
    return user


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=str(admin_user.id),
        role=admin_user.role,
        org_id=admin_user.org_id,
    )
    return {"Authorization": f"Bearer {token}"}


# ── Project fixture ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_project(test_user: User) -> Project:
    """A project owned by test_user, tagged for CFD domain."""
    from app.models.project import SimulationDomain
    project = Project(
        name="Test CFD Project",
        description="Fixture project for Phase 0 tests",
        domain_tags=[SimulationDomain.CFD],
        owner_id=str(test_user.id),
    )
    await project.insert()
    return project


# ── Twin fixture ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_twin(test_project: Project) -> DigitalTwin:
    """A geometric-fidelity DigitalTwin in test_project."""
    from app.models.project import SimulationDomain
    from app.models.twin import FidelityLevel, AiMode, GeometryFormat
    twin = DigitalTwin(
        project_id=str(test_project.id),
        name="Test Wing Geometry",
        domain=SimulationDomain.CFD,
        fidelity_level=FidelityLevel.GEOMETRIC,
        default_ai_mode=AiMode.PRINCIPLED_SOLVE,
        geometry_format=GeometryFormat.STEP,
    )
    await twin.insert()
    return twin
