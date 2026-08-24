from app.database.config import Settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

settings = Settings()

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL


engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    # Per-worker pool sizing. Aggregate ceiling = pool_size + max_overflow per
    # worker × gunicorn workers × ECS tasks. Keep the aggregate below RDS
    # max_connections with headroom for admin/replication/zombie slots.
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=60,
    pool_pre_ping=True,  # Validate connections before use (guards stale RDS conns)
    pool_recycle=3600,
    # Defense in depth for SQL logs/traces. Passive reading routes additionally
    # suppress dependency instrumentation because driver constraint details may
    # still echo a failing row even when bound parameters are hidden.
    hide_parameters=True,
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)
