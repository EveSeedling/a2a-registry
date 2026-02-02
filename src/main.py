"""
A2A Agent Registry - MVP

A public directory for A2A-compatible agents.
Fills the gap in the A2A spec for curated registry discovery.
"""

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session

from .database import get_db, init_db, AgentModel

app = FastAPI(
    title="A2A Agent Registry",
    description="A public directory for discovering A2A-compatible agents",
    version="0.1.0",
)

# CORS for web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Initialize database on startup
@app.on_event("startup")
def startup():
    init_db()


# ============ Models ============

class AgentSkill(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tags: list[str] = []
    examples: list[str] = []


class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False


class AgentCard(BaseModel):
    name: str
    description: str
    url: HttpUrl
    version: Optional[str] = None
    default_input_modes: list[str] = ["text"]
    default_output_modes: list[str] = ["text"]
    capabilities: Optional[AgentCapabilities] = None
    skills: list[AgentSkill] = []


class RegisteredAgent(BaseModel):
    id: str
    card: AgentCard
    registered_at: datetime
    last_seen: Optional[datetime] = None
    verified: bool = False

    class Config:
        from_attributes = True


class RegisterRequest(BaseModel):
    card: AgentCard


class RegisterResponse(BaseModel):
    success: bool
    agent_id: str
    message: str


# ============ Helper Functions ============

def agent_model_to_response(agent: AgentModel) -> dict:
    """Convert database model to API response."""
    return {
        "id": agent.id,
        "card": agent.card_json,
        "registered_at": agent.registered_at.isoformat() if agent.registered_at else None,
        "last_seen": agent.last_seen.isoformat() if agent.last_seen else None,
        "verified": agent.verified
    }


# ============ API Endpoints ============

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web UI."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return template_path.read_text()
    return HTMLResponse(content="<h1>A2A Agent Registry</h1><p>See <a href='/docs'>/docs</a> for API.</p>")


@app.get("/api")
async def api_info():
    """API information endpoint."""
    return {
        "name": "A2A Agent Registry",
        "version": "0.1.0",
        "description": "A public directory for discovering A2A-compatible agents",
        "endpoints": {
            "register": "POST /agents",
            "list": "GET /agents",
            "get": "GET /agents/{agent_id}",
            "search": "GET /agents/search",
        }
    }


@app.post("/agents", response_model=RegisterResponse)
async def register_agent(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new agent in the registry."""
    
    # Generate unique ID based on agent name (slugified)
    base_id = request.card.name.lower().replace(" ", "-").replace("_", "-")
    agent_id = base_id
    
    # Handle collisions
    counter = 1
    while db.query(AgentModel).filter(AgentModel.id == agent_id).first():
        agent_id = f"{base_id}-{counter}"
        counter += 1
    
    # Store the agent - serialize with mode='json' for proper JSON types
    card_dict = request.card.model_dump(mode='json')
    
    agent = AgentModel(
        id=agent_id,
        name=request.card.name,
        description=request.card.description,
        url=str(request.card.url),
        card_json=card_dict,
        registered_at=datetime.utcnow(),
        verified=False,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    
    return RegisterResponse(
        success=True,
        agent_id=agent_id,
        message=f"Agent '{request.card.name}' registered successfully",
    )


@app.get("/agents")
async def list_agents(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List all registered agents."""
    total = db.query(AgentModel).count()
    agents = db.query(AgentModel).offset(offset).limit(limit).all()
    
    return {
        "agents": [agent_model_to_response(a) for a in agents],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/agents/search")
async def search_agents(
    skill: Optional[str] = Query(default=None, description="Search by skill ID or name"),
    tag: Optional[str] = Query(default=None, description="Search by tag"),
    q: Optional[str] = Query(default=None, description="Full-text search in name/description"),
    capability: Optional[str] = Query(default=None, description="Filter by capability"),
    db: Session = Depends(get_db),
):
    """Search for agents by various criteria."""
    query = db.query(AgentModel)
    
    # Full-text search on name/description
    if q:
        q_lower = q.lower()
        query = query.filter(
            (AgentModel.name.ilike(f"%{q_lower}%")) |
            (AgentModel.description.ilike(f"%{q_lower}%"))
        )
    
    agents = query.all()
    results = []
    
    for agent in agents:
        card = agent.card_json
        
        # Skill filter (needs JSON inspection)
        if skill:
            skill_match = any(
                skill.lower() in s.get('id', '').lower() or 
                skill.lower() in s.get('name', '').lower()
                for s in card.get('skills', [])
            )
            if not skill_match:
                continue
        
        # Tag filter
        if tag:
            tag_match = any(
                tag.lower() in t.lower()
                for s in card.get('skills', [])
                for t in s.get('tags', [])
            )
            if not tag_match:
                continue
        
        # Capability filter
        if capability:
            caps = card.get('capabilities', {})
            if not caps.get(capability):
                continue
        
        results.append(agent_model_to_response(agent))
    
    return {
        "results": results,
        "count": len(results),
        "filters": {
            "skill": skill,
            "tag": tag,
            "q": q,
            "capability": capability,
        }
    }


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str, db: Session = Depends(get_db)):
    """Get a specific agent by ID."""
    agent = db.query(AgentModel).filter(AgentModel.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent_model_to_response(agent)


@app.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, db: Session = Depends(get_db)):
    """Remove an agent from the registry."""
    agent = db.query(AgentModel).filter(AgentModel.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.delete(agent)
    db.commit()
    return {"success": True, "message": f"Agent {agent_id} removed"}


@app.post("/validate")
async def validate_card(request: RegisterRequest):
    """Validate an Agent Card without registering it."""
    from .validator import validate_agent_card
    result = validate_agent_card(request.card.model_dump())
    return result


# ============ Run ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
