"""
EWC Compute — pytest fixtures for Phase 0 test suite.

Key fix vs previous version:
  The FastAPI lifespan calls init_db() and init_redis() on startup.
  LifespanManager triggers the lifespan, which would attempt real connections.
  This conftest patches init_db and init_redis at the module level BEFORE
  the app is imported, so the lifespan runs without any real I/O.
  Beanie and the Redis client are initialised directly with mocks here.
"""
import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from beanie import init_beanie
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.audit import AuditEvent
from app.models.project import Project, SimulationDomain
from app.models.sim_run import SimRun
from app.models.template import SimTemplate
from app.models.twin import AiMode, DigitalTwin, FidelityLevel, GeometryFormat
from app.models.user import SubscriptionTier, User, UserRole


# ── Event loop ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── In-memory database ──────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def mongo_mock():
    """
    Patches the database module with an in-memory mongomock-motor client.
    Also patches init_db / close_db so the lifespan never opens a real connection.
    """
    import app.core.database as db_module

    client = AsyncMongoMockClient()
    db = client[settings.MONGODB_DB_NAME]

    await init_beanie(
        database=db,
        document_models=[User, Project, DigitalTwin, SimTemplate, SimRun, AuditEvent],
    )

    db_module._client = client
    db_module._db = db

    # Patch init_db/close_db so lifespan doesn't touch real MongoDB
    with patch.object(db_module, "init_db", new=AsyncMock()), \
         patch.object(db_module, "close_db", new=AsyncMock()):
        yield db

    for name in await db.list_collection_names():
        await db.drop_collection(name)


@pytest_asyncio.fixture(autouse=True)
async def redis_mock():
    """
    Patches the cache module with fakeredis.
    Also patches init_redis / close_redis so lifespan never opens real Redis.
    """
    import app.core.cache as cache_module

    fake_redis = FakeRedis()
    cache_module._redis = fake_redis

    with patch.object(cache_module, "init_redis", new=AsyncMock()), \
         patch.object(cache_module, "close_redis", new=AsyncMock()):
        yield fake_redis

    await fake_redis.aclose()


# ── Test client ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def app_client(mongo_mock, redis_mock) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP test client. Uses ASGITransport — no real network.
    Lifespan runs but init_db / init_redis are mocked (see above).
    """
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# ── User fixtures ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_user() -> User:
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
    return create_access_token(str(test_user.id), test_user.role, test_user.org_id)


@pytest.fixture
def auth_headers(test_user_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {test_user_token}"}


@pytest_asyncio.fixture
async def admin_user() -> User:
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
    token = create_access_token(str(admin_user.id), admin_user.role, admin_user.org_id)
    return {"Authorization": f"Bearer {token}"}


# ── Project / Twin fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_project(test_user: User) -> Project:
    project = Project(
        name="Test CFD Project",
        description="Fixture project for Phase 0 tests",
        domain_tags=[SimulationDomain.CFD],
        owner_id=str(test_user.id),
    )
    await project.insert()
    return project


@pytest_asyncio.fixture
async def test_twin(test_project: Project) -> DigitalTwin:
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



