"""
Database configuration for A2A Registry.
Uses PostgreSQL via SQLAlchemy.
"""

import os
from sqlalchemy import create_engine, Column, String, DateTime, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# Get database URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./registry.db")

# Fix for Render's postgres:// vs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class AgentModel(Base):
    """Database model for registered agents."""
    __tablename__ = "agents"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    url = Column(String, nullable=False)
    card_json = Column(JSON, nullable=False)  # Full Agent Card as JSON
    registered_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=True)
    verified = Column(Boolean, default=False)


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI to get DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
