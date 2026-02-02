"""
A2A Agent Registry - MVP

A public directory for A2A-compatible agents.
Fills the gap in the A2A spec for curated registry discovery.
"""

from fastapi import FastAPI, HTTPException, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import secrets

from .database import get_db, init_db, AgentModel

app = FastAPI(
    title="A2A Agent Registry",
    description="A public directory for discovering A2A-compatible agents with real-time status",
    version="2.0.0",
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
    heartbeat_token: Optional[str] = None  # v2: token for sending heartbeats


# v2: Dynamic State models
class HeartbeatRequest(BaseModel):
    status: Optional[str] = Field(default="online", pattern="^(online|offline|busy)$")
    load: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    message: Optional[str] = Field(default=None, max_length=256)


class HeartbeatResponse(BaseModel):
    success: bool
    agent_id: str
    last_seen: datetime
    status: str


class DynamicState(BaseModel):
    """Agent's current runtime state."""
    status: str = "offline"
    load: Optional[float] = None
    message: Optional[str] = None
    last_seen: Optional[datetime] = None
    online: bool = False  # computed: seen within threshold


# ============ Constants ============

# How long before an agent is considered offline (minutes)
ONLINE_THRESHOLD_MINUTES = 5


# ============ Helper Functions ============

def is_agent_online(agent: AgentModel) -> bool:
    """Check if agent has been seen within the online threshold."""
    if not agent.last_seen:
        return False
    threshold = datetime.utcnow() - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
    return agent.last_seen > threshold


def agent_model_to_response(agent: AgentModel, include_state: bool = True) -> dict:
    """Convert database model to API response."""
    response = {
        "id": agent.id,
        "card": agent.card_json,
        "registered_at": agent.registered_at.isoformat() if agent.registered_at else None,
        "last_seen": agent.last_seen.isoformat() if agent.last_seen else None,
        "verified": agent.verified,
    }
    
    # v2: Include dynamic state
    if include_state:
        response["state"] = {
            "status": agent.status or "offline",
            "load": agent.load,
            "message": agent.status_message,
            "online": is_agent_online(agent),
        }
    
    return response


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
        "version": "2.0.0",
        "description": "A public directory for discovering A2A-compatible agents with real-time status",
        "endpoints": {
            "register": "POST /agents",
            "list": "GET /agents",
            "get": "GET /agents/{agent_id}",
            "search": "GET /agents/search",
            "heartbeat": "POST /agents/{agent_id}/heartbeat",  # v2
        },
        "v2_features": {
            "heartbeat": "Agents POST heartbeats to update live status",
            "online_filter": "GET /agents?online=true filters to agents seen in last 5 min",
            "status_filter": "GET /agents?status=busy filters by explicit status",
            "dynamic_state": "Agent responses include state.online, state.status, state.load",
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
    
    # v2: Generate heartbeat token for this agent
    heartbeat_token = secrets.token_urlsafe(32)
    
    agent = AgentModel(
        id=agent_id,
        name=request.card.name,
        description=request.card.description,
        url=str(request.card.url),
        card_json=card_dict,
        registered_at=datetime.utcnow(),
        verified=False,
        heartbeat_token=heartbeat_token,  # v2
        status="offline",  # v2
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    
    return RegisterResponse(
        success=True,
        agent_id=agent_id,
        message=f"Agent '{request.card.name}' registered successfully",
        heartbeat_token=heartbeat_token,  # v2: Return token to agent
    )


@app.get("/agents")
async def list_agents(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    online: Optional[bool] = Query(default=None, description="Filter by online status"),
    status: Optional[str] = Query(default=None, description="Filter by status (online/offline/busy)"),
    db: Session = Depends(get_db),
):
    """List all registered agents. Optionally filter by online/status."""
    query = db.query(AgentModel)
    
    # v2: Filter by online status (seen within threshold)
    if online is not None:
        threshold = datetime.utcnow() - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
        if online:
            query = query.filter(AgentModel.last_seen > threshold)
        else:
            query = query.filter(
                (AgentModel.last_seen == None) | (AgentModel.last_seen <= threshold)
            )
    
    # v2: Filter by explicit status
    if status:
        query = query.filter(AgentModel.status == status)
    
    total = query.count()
    agents = query.offset(offset).limit(limit).all()
    
    return {
        "agents": [agent_model_to_response(a) for a in agents],
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {
            "online": online,
            "status": status,
        }
    }


@app.get("/agents/search")
async def search_agents(
    skill: Optional[str] = Query(default=None, description="Search by skill ID or name"),
    tag: Optional[str] = Query(default=None, description="Search by tag"),
    q: Optional[str] = Query(default=None, description="Full-text search in name/description"),
    capability: Optional[str] = Query(default=None, description="Filter by capability"),
    online: Optional[bool] = Query(default=None, description="Filter by online status"),
    status: Optional[str] = Query(default=None, description="Filter by status (online/offline/busy)"),
    db: Session = Depends(get_db),
):
    """Search for agents by various criteria including live status."""
    query = db.query(AgentModel)
    
    # Full-text search on name/description
    if q:
        q_lower = q.lower()
        query = query.filter(
            (AgentModel.name.ilike(f"%{q_lower}%")) |
            (AgentModel.description.ilike(f"%{q_lower}%"))
        )
    
    # v2: Filter by online status
    if online is not None:
        threshold = datetime.utcnow() - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
        if online:
            query = query.filter(AgentModel.last_seen > threshold)
        else:
            query = query.filter(
                (AgentModel.last_seen == None) | (AgentModel.last_seen <= threshold)
            )
    
    # v2: Filter by explicit status
    if status:
        query = query.filter(AgentModel.status == status)
    
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
            "online": online,
            "status": status,
        }
    }


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str, db: Session = Depends(get_db)):
    """Get a specific agent by ID."""
    agent = db.query(AgentModel).filter(AgentModel.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent_model_to_response(agent)


@app.post("/agents/{agent_id}/heartbeat", response_model=HeartbeatResponse)
async def agent_heartbeat(
    agent_id: str,
    request: HeartbeatRequest = HeartbeatRequest(),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    Send a heartbeat to update agent's live status.
    
    Agents should call this every 1-2 minutes to be considered "online".
    Requires the heartbeat_token returned at registration in the Authorization header.
    
    Example: Authorization: Bearer <heartbeat_token>
    """
    agent = db.query(AgentModel).filter(AgentModel.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Verify heartbeat token
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    # Extract token from "Bearer <token>" format
    token = authorization.replace("Bearer ", "").strip()
    if not token or token != agent.heartbeat_token:
        raise HTTPException(status_code=403, detail="Invalid heartbeat token")
    
    # Update agent state
    now = datetime.utcnow()
    agent.last_seen = now
    agent.status = request.status or "online"
    
    if request.load is not None:
        agent.load = request.load
    
    if request.message is not None:
        agent.status_message = request.message
    
    db.commit()
    db.refresh(agent)
    
    return HeartbeatResponse(
        success=True,
        agent_id=agent_id,
        last_seen=agent.last_seen,
        status=agent.status,
    )


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
