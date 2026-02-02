"""
A2A Agent Card Validator

Validates Agent Cards against the A2A Protocol specification.
Can be used standalone or integrated with the registry.
"""

from pydantic import BaseModel, HttpUrl, ValidationError, field_validator
from typing import Optional
import json
import httpx


class AgentSkill(BaseModel):
    """A skill that an agent can perform."""
    id: str
    name: str
    description: Optional[str] = None
    tags: list[str] = []
    examples: list[str] = []
    
    @field_validator('id')
    @classmethod
    def id_must_be_valid(cls, v):
        if not v or not v.strip():
            raise ValueError('Skill id cannot be empty')
        if ' ' in v:
            raise ValueError('Skill id should not contain spaces (use hyphens or underscores)')
        return v


class AgentCapabilities(BaseModel):
    """Capabilities that the agent supports."""
    streaming: bool = False
    pushNotifications: bool = False


class AgentCard(BaseModel):
    """
    Agent Card - the digital business card for an A2A agent.
    
    Based on A2A Protocol specification.
    """
    name: str
    description: str
    url: HttpUrl
    version: Optional[str] = None
    defaultInputModes: list[str] = ["text"]
    defaultOutputModes: list[str] = ["text"]
    capabilities: Optional[AgentCapabilities] = None
    skills: list[AgentSkill] = []
    
    # Optional metadata
    provider: Optional[dict] = None
    documentation: Optional[str] = None
    contacts: Optional[dict] = None
    
    @field_validator('name')
    @classmethod
    def name_must_be_valid(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters')
        if len(v) > 100:
            raise ValueError('Name must be less than 100 characters')
        return v.strip()
    
    @field_validator('description')
    @classmethod
    def description_must_be_valid(cls, v):
        if not v or len(v.strip()) < 10:
            raise ValueError('Description must be at least 10 characters')
        if len(v) > 1000:
            raise ValueError('Description must be less than 1000 characters')
        return v.strip()


class ValidationResult(BaseModel):
    """Result of validating an Agent Card."""
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    card: Optional[dict] = None


def validate_agent_card(card_data: dict) -> ValidationResult:
    """
    Validate an Agent Card against the A2A specification.
    
    Args:
        card_data: Dictionary containing the Agent Card data
        
    Returns:
        ValidationResult with valid status, errors, and warnings
    """
    errors = []
    warnings = []
    
    try:
        # Validate against Pydantic model
        card = AgentCard(**card_data)
        
        # Additional semantic checks
        
        # Check for at least one skill
        if not card.skills:
            warnings.append("Agent has no skills defined. Consider adding skills to help discovery.")
        
        # Check URL is HTTPS in production
        if str(card.url).startswith('http://') and 'localhost' not in str(card.url):
            warnings.append("URL uses HTTP instead of HTTPS. Consider using HTTPS for production.")
        
        # Check for version
        if not card.version:
            warnings.append("No version specified. Consider adding a version for tracking changes.")
        
        # Check skills have descriptions
        for skill in card.skills:
            if not skill.description:
                warnings.append(f"Skill '{skill.id}' has no description.")
            if not skill.examples:
                warnings.append(f"Skill '{skill.id}' has no examples. Examples help other agents understand usage.")
        
        return ValidationResult(
            valid=True,
            errors=[],
            warnings=warnings,
            card=card.model_dump()
        )
        
    except ValidationError as e:
        for error in e.errors():
            field = '.'.join(str(x) for x in error['loc'])
            msg = error['msg']
            errors.append(f"{field}: {msg}")
        
        return ValidationResult(
            valid=False,
            errors=errors,
            warnings=warnings,
            card=None
        )


async def validate_endpoint(url: str) -> dict:
    """
    Check if an agent endpoint is reachable and has a valid Agent Card.
    
    Args:
        url: The agent's base URL
        
    Returns:
        Dict with reachable status and any discovered Agent Card
    """
    result = {
        "reachable": False,
        "has_well_known": False,
        "agent_card": None,
        "error": None
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try the well-known endpoint
            well_known_url = f"{url.rstrip('/')}/.well-known/agent-card.json"
            response = await client.get(well_known_url)
            
            result["reachable"] = True
            
            if response.status_code == 200:
                result["has_well_known"] = True
                try:
                    result["agent_card"] = response.json()
                except json.JSONDecodeError:
                    result["error"] = "Invalid JSON at well-known endpoint"
            else:
                result["error"] = f"Well-known endpoint returned {response.status_code}"
                
    except httpx.TimeoutException:
        result["error"] = "Connection timed out"
    except httpx.ConnectError:
        result["error"] = "Could not connect to endpoint"
    except Exception as e:
        result["error"] = str(e)
    
    return result


# CLI for standalone use
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python validator.py <agent-card.json>")
        print("       python validator.py --url <agent-url>")
        sys.exit(1)
    
    if sys.argv[1] == "--url":
        import asyncio
        url = sys.argv[2]
        print(f"Checking endpoint: {url}")
        result = asyncio.run(validate_endpoint(url))
        print(json.dumps(result, indent=2))
    else:
        with open(sys.argv[1]) as f:
            card_data = json.load(f)
        
        result = validate_agent_card(card_data)
        print(f"Valid: {result.valid}")
        
        if result.errors:
            print("\nErrors:")
            for e in result.errors:
                print(f"  ❌ {e}")
        
        if result.warnings:
            print("\nWarnings:")
            for w in result.warnings:
                print(f"  ⚠️  {w}")
        
        if result.valid:
            print("\n✅ Agent Card is valid!")
