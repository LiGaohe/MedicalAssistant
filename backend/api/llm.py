from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from ..database import get_db
from ..services.llm import LLMService
from ..models.llm_config import LLMConfig

router = APIRouter(prefix="/api/llm", tags=["llm"])


class GenerateRequest(BaseModel):
    prompt: str
    config_name: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


class GenerateWithTemplateRequest(BaseModel):
    template_name: str
    config_name: Optional[str] = None
    variables: Dict[str, Any]


class ConfigCreate(BaseModel):
    config_name: str
    provider: str
    model_name: str
    api_key: Optional[str] = None
    api_endpoint: Optional[str] = None
    max_tokens: int = 2048
    temperature: str = "0.7"
    is_active: bool = True


class ConfigUpdate(BaseModel):
    is_active: Optional[bool] = None


@router.post("/generate")
async def generate_text(
    request: GenerateRequest,
    db: Session = Depends(get_db)
):
    try:
        service = LLMService(db)
        response = service.generate(
            prompt=request.prompt,
            config_name=request.config_name,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )
        return {
            "text": response.text,
            "model": response.model,
            "provider": response.provider,
            "usage": response.usage
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-with-template")
async def generate_with_template(
    request: GenerateWithTemplateRequest,
    db: Session = Depends(get_db)
):
    try:
        service = LLMService(db)
        response = service.generate_with_template(
            template_name=request.template_name,
            config_name=request.config_name,
            **request.variables
        )
        return {
            "text": response.text,
            "model": response.model,
            "provider": response.provider,
            "usage": response.usage
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def get_available_models(db: Session = Depends(get_db)):
    service = LLMService(db)
    return {"models": service.get_available_models()}


@router.get("/configs")
async def get_configs(db: Session = Depends(get_db)):
    configs = db.query(LLMConfig).all()
    return {"configs": [config.to_dict() for config in configs]}


@router.post("/config")
async def create_config(
    config: ConfigCreate,
    db: Session = Depends(get_db)
):
    existing = db.query(LLMConfig).filter(
        LLMConfig.config_name == config.config_name
    ).first()
    
    if existing:
        existing.provider = config.provider
        existing.model_name = config.model_name
        existing.api_key = config.api_key
        existing.api_endpoint = config.api_endpoint
        existing.max_tokens = config.max_tokens
        existing.temperature = config.temperature
        existing.is_active = config.is_active
        db.commit()
        db.refresh(existing)
        return {"success": True, "config_id": existing.id, "message": "配置更新成功"}
    
    new_config = LLMConfig(
        config_name=config.config_name,
        provider=config.provider,
        model_name=config.model_name,
        api_key=config.api_key,
        api_endpoint=config.api_endpoint,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        is_active=config.is_active
    )
    
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    
    return {"success": True, "config_id": new_config.id, "message": "配置创建成功"}


@router.put("/config/{config_id}")
async def update_config(
    config_id: int,
    config: ConfigUpdate,
    db: Session = Depends(get_db)
):
    existing = db.query(LLMConfig).filter(LLMConfig.id == config_id).first()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Config not found")
    
    if config.is_active is not None:
        existing.is_active = config.is_active
    
    db.commit()
    db.refresh(existing)
    
    return {"success": True, "config": existing.to_dict()}


@router.delete("/config/{config_id}")
async def delete_config(
    config_id: int,
    db: Session = Depends(get_db)
):
    config = db.query(LLMConfig).filter(LLMConfig.id == config_id).first()
    
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    
    db.delete(config)
    db.commit()
    
    return {"success": True, "message": "配置删除成功"}
