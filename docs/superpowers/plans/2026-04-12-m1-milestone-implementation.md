# M1里程碑实现计划：音频到转写闭环

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现从音频上传到标准化转写结果的完整闭环，包含说话人分离和ASR纠错功能

**Architecture:** 采用FastAPI后端 + 纯HTML前端 + SQLite数据库的三层架构，集成现有FunASR模块，实现渐进式开发

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, FunASR, HTML/JavaScript

---

## 文件结构

```
backend/
├── __init__.py                 # 包初始化
├── main.py                     # FastAPI应用入口
├── config.py                   # 配置管理
├── database.py                 # 数据库连接
├── models/
│   ├── __init__.py            # 模型包初始化
│   ├── visit.py               # 就诊记录模型
│   ├── transcript.py          # 转写记录模型
│   └── task.py                # 任务状态模型
├── api/
│   ├── __init__.py            # API包初始化
│   ├── upload.py              # 上传接口
│   ├── asr.py                 # ASR转写接口
│   └── task.py                # 任务状态接口
├── services/
│   ├── __init__.py            # 服务包初始化
│   ├── asr_service.py         # ASR服务
│   ├── postprocessor.py       # ASR后处理
│   └── normalizer.py          # 结果标准化
└── utils/
    ├── __init__.py            # 工具包初始化
    └── audio_utils.py         # 音频处理工具

frontend/
├── index.html                 # 上传页面
├── result.html                # 结果展示页面
├── css/
│   └── style.css              # 样式文件
└── js/
    ├── upload.js              # 上传逻辑
    └── result.js              # 结果展示逻辑

data/
├── audio/                     # 音频文件存储
├── database/                  # SQLite数据库文件
└── logs/                      # 日志文件

config/
└── asr_correction_rules.json  # ASR纠错规则

requirements.txt               # Python依赖
```

---

## 阶段1：基础框架

### Task 1: 创建项目目录结构

**Files:**
- Create: `backend/__init__.py`
- Create: `backend/models/__init__.py`
- Create: `backend/api/__init__.py`
- Create: `backend/services/__init__.py`
- Create: `backend/utils/__init__.py`
- Create: `data/audio/.gitkeep`
- Create: `data/database/.gitkeep`
- Create: `data/logs/.gitkeep`

- [ ] **Step 1: 创建backend包初始化文件**

```python
# backend/__init__.py
"""中文门诊病历生成系统后端"""
__version__ = "1.0.0"
```

- [ ] **Step 2: 创建models包初始化文件**

```python
# backend/models/__init__.py
"""数据模型"""
from .visit import Visit
from .transcript import TranscriptTurn, ASRCorrection
from .task import Task

__all__ = ["Visit", "TranscriptTurn", "ASRCorrection", "Task"]
```

- [ ] **Step 3: 创建api包初始化文件**

```python
# backend/api/__init__.py
"""API路由"""
from .upload import router as upload_router
from .asr import router as asr_router
from .task import router as task_router

__all__ = ["upload_router", "asr_router", "task_router"]
```

- [ ] **Step 4: 创建services包初始化文件**

```python
# backend/services/__init__.py
"""业务逻辑服务"""
from .asr_service import ASRService
from .postprocessor import ASRPostprocessor
from .normalizer import TranscriptNormalizer

__all__ = ["ASRService", "ASRPostprocessor", "TranscriptNormalizer"]
```

- [ ] **Step 5: 创建utils包初始化文件**

```python
# backend/utils/__init__.py
"""工具函数"""
from .audio_utils import get_audio_duration, validate_audio_file

__all__ = ["get_audio_duration", "validate_audio_file"]
```

- [ ] **Step 6: 创建数据目录**

```bash
mkdir -p data/audio data/database data/logs
touch data/audio/.gitkeep data/database/.gitkeep data/logs/.gitkeep
```

- [ ] **Step 7: 提交目录结构**

```bash
git add backend/ data/
git commit -m "feat: 创建项目目录结构"
```

---

### Task 2: 创建配置管理模块

**Files:**
- Create: `backend/config.py`

- [ ] **Step 1: 创建配置类**

```python
# backend/config.py
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    APP_NAME: str = "中文门诊病历生成系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    DATABASE_URL: str = "sqlite:///data/database/medical.db"
    
    AUDIO_STORAGE_PATH: str = "data/audio"
    MAX_AUDIO_SIZE: int = 100 * 1024 * 1024
    
    ASR_ENGINE: str = "funasr"
    ASR_DEVICE: str = "cpu"
    HOTWORD_PATH: str = "config/hotwords_medical.txt"
    
    ENABLE_DIARIZATION: bool = True
    ENABLE_ASR_CORRECTION: bool = True
    CORRECTION_CONFIDENCE_THRESHOLD: float = 0.7
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
```

- [ ] **Step 2: 提交配置模块**

```bash
git add backend/config.py
git commit -m "feat: 添加配置管理模块"
```

---

### Task 3: 创建数据库连接模块

**Files:**
- Create: `backend/database.py`

- [ ] **Step 1: 创建数据库连接类**

```python
# backend/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path

from .config import settings


Path("data/database").mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from .models import Visit, TranscriptTurn, Task, ASRCorrection
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 2: 提交数据库模块**

```bash
git add backend/database.py
git commit -m "feat: 添加数据库连接模块"
```

---

### Task 4: 创建数据模型

**Files:**
- Create: `backend/models/visit.py`
- Create: `backend/models/transcript.py`
- Create: `backend/models/task.py`

- [ ] **Step 1: 创建Visit模型**

```python
# backend/models/visit.py
from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class Visit(Base):
    __tablename__ = "visits"
    
    visit_id = Column(String, primary_key=True, index=True)
    patient_name = Column(String, nullable=True)
    visit_date = Column(String, nullable=True)
    audio_path = Column(String, nullable=False)
    audio_duration = Column(Float, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    turns = relationship("TranscriptTurn", back_populates="visit", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="visit", cascade="all, delete-orphan")
    corrections = relationship("ASRCorrection", back_populates="visit", cascade="all, delete-orphan")
```

- [ ] **Step 2: 创建TranscriptTurn和ASRCorrection模型**

```python
# backend/models/transcript.py
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"
    
    turn_id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    turn_index = Column(Integer, nullable=False)
    speaker = Column(String, nullable=False)
    text = Column(String, nullable=False)
    original_text = Column(String, nullable=True)
    corrected_text = Column(String, nullable=True)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="turns")
    corrections = relationship("ASRCorrection", back_populates="turn", cascade="all, delete-orphan")


class ASRCorrection(Base):
    __tablename__ = "asr_corrections"
    
    correction_id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    turn_id = Column(Integer, ForeignKey("transcript_turns.turn_id"), nullable=False)
    original_word = Column(String, nullable=False)
    corrected_word = Column(String, nullable=False)
    correction_type = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="corrections")
    turn = relationship("TranscriptTurn", back_populates="corrections")
```

- [ ] **Step 3: 创建Task模型**

```python
# backend/models/task.py
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class Task(Base):
    __tablename__ = "tasks"
    
    task_id = Column(String, primary_key=True, index=True)
    visit_id = Column(String, ForeignKey("visits.visit_id"), nullable=False)
    task_type = Column(String, nullable=False)
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    visit = relationship("Visit", back_populates="tasks")
```

- [ ] **Step 4: 提交数据模型**

```bash
git add backend/models/
git commit -m "feat: 添加数据模型"
```

---

### Task 5: 创建音频处理工具

**Files:**
- Create: `backend/utils/audio_utils.py`

- [ ] **Step 1: 创建音频工具函数**

```python
# backend/utils/audio_utils.py
from pathlib import Path
from typing import Tuple


def get_audio_duration(audio_path: str | Path) -> float:
    try:
        import librosa
        duration, _ = librosa.duration(path=str(audio_path))
        return duration
    except Exception:
        return 0.0


def validate_audio_file(file_path: str | Path, max_size: int) -> Tuple[bool, str]:
    path = Path(file_path)
    
    if not path.exists():
        return False, "文件不存在"
    
    if path.suffix.lower() not in [".wav", ".mp3"]:
        return False, "不支持的音频格式，仅支持wav和mp3"
    
    file_size = path.stat().st_size
    if file_size > max_size:
        return False, f"文件大小超过限制（最大{max_size // 1024 // 1024}MB）"
    
    return True, "验证通过"


def convert_to_wav(audio_path: str | Path, output_path: str | Path) -> Path:
    try:
        import librosa
        import soundfile as sf
        
        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        sf.write(str(output_path), y, sr)
        return output_path
    except Exception as e:
        raise RuntimeError(f"音频转换失败: {e}")
```

- [ ] **Step 2: 提交音频工具**

```bash
git add backend/utils/audio_utils.py
git commit -m "feat: 添加音频处理工具"
```

---

### Task 6: 创建ASR服务

**Files:**
- Create: `backend/services/asr_service.py`

- [ ] **Step 1: 创建ASR服务类**

```python
# backend/services/asr_service.py
from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.asr import FunASREngine


class ASRService:
    def __init__(self, config: dict):
        self.config = config
        self.engine: Optional[FunASREngine] = None
    
    def initialize(self):
        if self.engine is None:
            self.engine = FunASREngine(
                device=self.config.get("device", "cpu"),
                hotword_path=self.config.get("hotword_path")
            )
            self.engine.load_model()
    
    def transcribe(self, audio_path: str | Path) -> dict:
        if self.engine is None:
            self.initialize()
        
        result = self.engine.transcribe(audio_path)
        
        return {
            "text": result.text,
            "segments": result.segments,
            "duration": result.duration_seconds,
            "inference_time": result.inference_time
        }
    
    def transcribe_with_diarization(self, audio_path: str | Path) -> dict:
        if self.engine is None:
            self.initialize()
        
        result = self.engine.transcribe(audio_path)
        
        turns = []
        if result.segments:
            for i, segment in enumerate(result.segments):
                speaker = self._map_speaker(i)
                turns.append({
                    "turn_index": i,
                    "speaker": speaker,
                    "text": segment.get("text", ""),
                    "start_ms": int(segment.get("start", 0) * 1000),
                    "end_ms": int(segment.get("end", 0) * 1000),
                    "confidence": segment.get("confidence", 0.0)
                })
        else:
            turns.append({
                "turn_index": 0,
                "speaker": "unknown",
                "text": result.text,
                "start_ms": 0,
                "end_ms": int(result.duration_seconds * 1000),
                "confidence": 0.0
            })
        
        return {
            "turns": turns,
            "duration": result.duration_seconds,
            "inference_time": result.inference_time
        }
    
    def _map_speaker(self, index: int) -> str:
        if index % 2 == 0:
            return "doctor"
        else:
            return "patient"
```

- [ ] **Step 2: 提交ASR服务**

```bash
git add backend/services/asr_service.py
git commit -m "feat: 添加ASR服务"
```

---

### Task 7: 创建上传接口

**Files:**
- Create: `backend/api/upload.py`

- [ ] **Step 1: 创建上传路由**

```python
# backend/api/upload.py
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import uuid
import shutil
from datetime import datetime

from ..database import get_db
from ..models.visit import Visit
from ..models.task import Task
from ..config import settings
from ..utils.audio_utils import get_audio_duration, validate_audio_file

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload")
async def upload_audio(
    audio_file: UploadFile = File(...),
    patient_name: str = Form(None),
    visit_date: str = Form(None),
    db: Session = Depends(get_db)
):
    visit_id = str(uuid.uuid4())
    
    file_ext = Path(audio_file.filename).suffix.lower()
    if file_ext not in [".wav", ".mp3"]:
        raise HTTPException(status_code=400, detail="仅支持wav和mp3格式")
    
    audio_storage = Path(settings.AUDIO_STORAGE_PATH)
    audio_storage.mkdir(parents=True, exist_ok=True)
    
    audio_path = audio_storage / f"{visit_id}{file_ext}"
    
    with open(audio_path, "wb") as buffer:
        shutil.copyfileobj(audio_file.file, buffer)
    
    is_valid, message = validate_audio_file(audio_path, settings.MAX_AUDIO_SIZE)
    if not is_valid:
        audio_path.unlink()
        raise HTTPException(status_code=400, detail=message)
    
    audio_duration = get_audio_duration(audio_path)
    
    visit = Visit(
        visit_id=visit_id,
        patient_name=patient_name,
        visit_date=visit_date or datetime.now().strftime("%Y-%m-%d"),
        audio_path=str(audio_path),
        audio_duration=audio_duration,
        status="pending"
    )
    db.add(visit)
    
    task_id = str(uuid.uuid4())
    task = Task(
        task_id=task_id,
        visit_id=visit_id,
        task_type="upload",
        status="completed",
        progress=100
    )
    db.add(task)
    
    db.commit()
    
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "visit_id": visit_id,
            "audio_path": str(audio_path),
            "audio_duration": audio_duration,
            "message": "音频上传成功"
        }
    )
```

- [ ] **Step 2: 提交上传接口**

```bash
git add backend/api/upload.py
git commit -m "feat: 添加音频上传接口"
```

---

### Task 8: 创建ASR转写接口

**Files:**
- Create: `backend/api/asr.py`

- [ ] **Step 1: 创建ASR路由**

```python
# backend/api/asr.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import uuid

from ..database import get_db
from ..models.visit import Visit
from ..models.task import Task
from ..models.transcript import TranscriptTurn
from ..services.asr_service import ASRService
from ..services.postprocessor import ASRPostprocessor
from ..services.normalizer import TranscriptNormalizer
from ..config import settings

router = APIRouter(prefix="/api/asr", tags=["asr"])

asr_service = ASRService({
    "device": settings.ASR_DEVICE,
    "hotword_path": settings.HOTWORD_PATH
})

postprocessor = ASRPostprocessor()
normalizer = TranscriptNormalizer()


def process_asr_task(visit_id: str, db_url: str):
    from ..database import SessionLocal
    
    db = SessionLocal()
    try:
        visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
        if not visit:
            return
        
        task = db.query(Task).filter(
            Task.visit_id == visit_id,
            Task.task_type == "asr"
        ).first()
        
        if not task:
            return
        
        task.status = "running"
        task.progress = 10
        db.commit()
        
        result = asr_service.transcribe_with_diarization(visit.audio_path)
        task.progress = 50
        db.commit()
        
        turns = normalizer.normalize(result["turns"])
        task.progress = 70
        db.commit()
        
        for turn in turns:
            corrected_text, corrections = postprocessor.correct(turn["text"])
            turn["corrected_text"] = corrected_text
            
            transcript_turn = TranscriptTurn(
                visit_id=visit_id,
                turn_index=turn["turn_index"],
                speaker=turn["speaker"],
                text=turn["text"],
                original_text=turn["original_text"],
                corrected_text=turn["corrected_text"],
                start_ms=turn["start_ms"],
                end_ms=turn["end_ms"],
                confidence=turn["confidence"]
            )
            db.add(transcript_turn)
        
        task.status = "completed"
        task.progress = 100
        visit.status = "completed"
        db.commit()
        
    except Exception as e:
        task.status = "failed"
        task.error_message = str(e)
        visit.status = "failed"
        db.commit()
    finally:
        db.close()


@router.post("/transcribe/{visit_id}")
async def transcribe_audio(
    visit_id: str,
    background_tasks: BackgroundTasks,
    enable_diarization: bool = True,
    enable_correction: bool = True,
    db: Session = Depends(get_db)
):
    visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="就诊记录不存在")
    
    if visit.status == "processing":
        raise HTTPException(status_code=400, detail="该音频正在处理中")
    
    task_id = str(uuid.uuid4())
    task = Task(
        task_id=task_id,
        visit_id=visit_id,
        task_type="asr",
        status="pending",
        progress=0
    )
    db.add(task)
    
    visit.status = "processing"
    db.commit()
    
    background_tasks.add_task(process_asr_task, visit_id, settings.DATABASE_URL)
    
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "visit_id": visit_id,
            "task_id": task_id,
            "status": "processing",
            "message": "ASR转写任务已启动"
        }
    )
```

- [ ] **Step 2: 提交ASR接口**

```bash
git add backend/api/asr.py
git commit -m "feat: 添加ASR转写接口"
```

---

### Task 9: 创建任务状态接口

**Files:**
- Create: `backend/api/task.py`

- [ ] **Step 1: 创建任务路由**

```python
# backend/api/task.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.task import Task
from ..models.transcript import TranscriptTurn

router = APIRouter(prefix="/api", tags=["task"])


@router.get("/task/{task_id}")
async def get_task_status(
    task_id: str,
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return JSONResponse(
        status_code=200,
        content={
            "task_id": task.task_id,
            "visit_id": task.visit_id,
            "task_type": task.task_type,
            "status": task.status,
            "progress": task.progress,
            "error_message": task.error_message,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None
        }
    )


@router.get("/transcript/{visit_id}")
async def get_transcript(
    visit_id: str,
    db: Session = Depends(get_db)
):
    from ..models.visit import Visit
    
    visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="就诊记录不存在")
    
    turns = db.query(TranscriptTurn).filter(
        TranscriptTurn.visit_id == visit_id
    ).order_by(TranscriptTurn.turn_index).all()
    
    turns_data = []
    for turn in turns:
        turns_data.append({
            "turn_id": turn.turn_id,
            "turn_index": turn.turn_index,
            "speaker": turn.speaker,
            "text": turn.text,
            "original_text": turn.original_text,
            "corrected_text": turn.corrected_text,
            "start_ms": turn.start_ms,
            "end_ms": turn.end_ms,
            "confidence": turn.confidence
        })
    
    return JSONResponse(
        status_code=200,
        content={
            "visit_id": visit.visit_id,
            "status": visit.status,
            "audio_duration": visit.audio_duration,
            "turns": turns_data
        }
    )
```

- [ ] **Step 2: 提交任务接口**

```bash
git add backend/api/task.py
git commit -m "feat: 添加任务状态接口"
```

---

### Task 10: 创建FastAPI主应用

**Files:**
- Create: `backend/main.py`

- [ ] **Step 1: 创建FastAPI应用**

```python
# backend/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .config import settings
from .database import init_db
from .api import upload_router, asr_router, task_router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

app.include_router(upload_router)
app.include_router(asr_router)
app.include_router(task_router)

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


@app.on_event("startup")
async def startup_event():
    init_db()


@app.get("/")
async def root():
    index_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "中文门诊病历生成系统", "version": settings.APP_VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 2: 提交主应用**

```bash
git add backend/main.py
git commit -m "feat: 添加FastAPI主应用"
```

---

### Task 11: 创建前端上传页面

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/css/style.css`
- Create: `frontend/js/upload.js`

- [ ] **Step 1: 创建HTML页面**

```html
<!-- frontend/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>中文门诊病历生成系统</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <h1>中文门诊病历生成系统</h1>
        
        <div class="upload-section">
            <div class="drop-zone" id="dropZone">
                <p>拖拽音频文件到此处</p>
                <p>或点击选择文件</p>
                <p class="hint">支持: wav, mp3</p>
                <input type="file" id="audioFile" accept=".wav,.mp3" hidden>
            </div>
            
            <div class="form-group">
                <label for="patientName">患者姓名:</label>
                <input type="text" id="patientName" placeholder="可选">
            </div>
            
            <div class="form-group">
                <label for="visitDate">就诊日期:</label>
                <input type="date" id="visitDate">
            </div>
            
            <button id="uploadBtn" class="btn-primary" disabled>开始上传</button>
            
            <div class="progress-section" id="progressSection" style="display: none;">
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
                <p id="progressText">上传进度: 0%</p>
            </div>
        </div>
    </div>
    
    <script src="/static/js/upload.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建CSS样式**

```css
/* frontend/css/style.css */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background-color: #f5f5f5;
    padding: 20px;
}

.container {
    max-width: 800px;
    margin: 0 auto;
    background: white;
    padding: 40px;
    border-radius: 8px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

h1 {
    text-align: center;
    color: #333;
    margin-bottom: 30px;
}

.upload-section {
    margin-top: 20px;
}

.drop-zone {
    border: 2px dashed #ccc;
    border-radius: 8px;
    padding: 60px 20px;
    text-align: center;
    cursor: pointer;
    transition: all 0.3s;
}

.drop-zone:hover {
    border-color: #4CAF50;
    background-color: #f9f9f9;
}

.drop-zone.dragover {
    border-color: #4CAF50;
    background-color: #e8f5e9;
}

.drop-zone p {
    margin: 10px 0;
    color: #666;
}

.drop-zone .hint {
    font-size: 14px;
    color: #999;
}

.form-group {
    margin-top: 20px;
}

.form-group label {
    display: block;
    margin-bottom: 8px;
    color: #333;
    font-weight: 500;
}

.form-group input {
    width: 100%;
    padding: 12px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 14px;
}

.btn-primary {
    width: 100%;
    padding: 14px;
    background-color: #4CAF50;
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 16px;
    cursor: pointer;
    margin-top: 20px;
    transition: background-color 0.3s;
}

.btn-primary:hover:not(:disabled) {
    background-color: #45a049;
}

.btn-primary:disabled {
    background-color: #ccc;
    cursor: not-allowed;
}

.progress-section {
    margin-top: 20px;
}

.progress-bar {
    width: 100%;
    height: 20px;
    background-color: #e0e0e0;
    border-radius: 10px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    background-color: #4CAF50;
    width: 0%;
    transition: width 0.3s;
}

#progressText {
    text-align: center;
    margin-top: 10px;
    color: #666;
}
```

- [ ] **Step 3: 创建JavaScript逻辑**

```javascript
// frontend/js/upload.js
document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.getElementById('dropZone');
    const audioFile = document.getElementById('audioFile');
    const uploadBtn = document.getElementById('uploadBtn');
    const progressSection = document.getElementById('progressSection');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const visitDate = document.getElementById('visitDate');
    
    const today = new Date().toISOString().split('T')[0];
    visitDate.value = today;
    
    let selectedFile = null;
    
    dropZone.addEventListener('click', () => audioFile.click());
    
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });
    
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileSelect(files[0]);
        }
    });
    
    audioFile.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });
    
    function handleFileSelect(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (ext !== 'wav' && ext !== 'mp3') {
            alert('仅支持wav和mp3格式');
            return;
        }
        
        selectedFile = file;
        dropZone.innerHTML = `<p>已选择: ${file.name}</p><p class="hint">点击重新选择</p>`;
        uploadBtn.disabled = false;
    }
    
    uploadBtn.addEventListener('click', async () => {
        if (!selectedFile) {
            alert('请先选择音频文件');
            return;
        }
        
        uploadBtn.disabled = true;
        progressSection.style.display = 'block';
        
        const formData = new FormData();
        formData.append('audio_file', selectedFile);
        formData.append('patient_name', document.getElementById('patientName').value);
        formData.append('visit_date', visitDate.value);
        
        try {
            progressFill.style.width = '30%';
            progressText.textContent = '上传进度: 30%';
            
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                progressFill.style.width = '100%';
                progressText.textContent = '上传成功！正在跳转...';
                
                setTimeout(() => {
                    window.location.href = `/static/result.html?visit_id=${result.visit_id}`;
                }, 1000);
            } else {
                throw new Error(result.message || '上传失败');
            }
        } catch (error) {
            alert('上传失败: ' + error.message);
            uploadBtn.disabled = false;
            progressSection.style.display = 'none';
        }
    });
});
```

- [ ] **Step 4: 提交前端页面**

```bash
git add frontend/
git commit -m "feat: 添加前端上传页面"
```

---

### Task 12: 创建依赖文件

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1: 创建requirements.txt**

```
# requirements.txt
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6
sqlalchemy>=2.0.0
pydantic-settings>=2.0.0
funasr>=1.0.0
modelscope>=1.10.0
librosa>=0.10.0
soundfile>=0.12.0
pypinyin>=0.49.0
python-Levenshtein>=0.21.0
```

- [ ] **Step 2: 提交依赖文件**

```bash
git add requirements.txt
git commit -m "feat: 添加项目依赖"
```

---

## 阶段2：ASR增强

### Task 13: 创建ASR后处理纠错模块

**Files:**
- Create: `backend/services/postprocessor.py`

- [ ] **Step 1: 创建ASR后处理类**

```python
# backend/services/postprocessor.py
import json
from pathlib import Path
from typing import Tuple, List, Dict


class ASRPostprocessor:
    def __init__(self, rules_path: str = "config/asr_correction_rules.json"):
        self.rules_path = Path(rules_path)
        self.rules = self._load_rules()
        self.correction_index = self._build_correction_index()
    
    def _load_rules(self) -> dict:
        if self.rules_path.exists():
            with open(self.rules_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"medical_terms": {}, "pinyin_similar": {}}
    
    def _build_correction_index(self) -> dict:
        index = {}
        
        for standard_term, variants in self.rules.get("medical_terms", {}).items():
            for variant in variants:
                index[variant] = {
                    "standard": standard_term,
                    "type": "medical_term",
                    "confidence": 0.9
                }
        
        for standard_term, variants in self.rules.get("pinyin_similar", {}).items():
            for variant in variants:
                index[variant] = {
                    "standard": standard_term,
                    "type": "pinyin_similar",
                    "confidence": 0.8
                }
        
        return index
    
    def correct(self, text: str) -> Tuple[str, List[Dict]]:
        corrections = []
        corrected_text = text
        
        for wrong_word, correction_info in self.correction_index.items():
            if wrong_word in corrected_text:
                corrected_text = corrected_text.replace(
                    wrong_word,
                    correction_info["standard"]
                )
                corrections.append({
                    "original": wrong_word,
                    "corrected": correction_info["standard"],
                    "type": correction_info["type"],
                    "confidence": correction_info["confidence"]
                })
        
        return corrected_text, corrections
```

- [ ] **Step 2: 提交后处理模块**

```bash
git add backend/services/postprocessor.py
git commit -m "feat: 添加ASR后处理纠错模块"
```

---

### Task 14: 创建转写结果标准化模块

**Files:**
- Create: `backend/services/normalizer.py`

- [ ] **Step 1: 创建标准化类**

```python
# backend/services/normalizer.py
import re
from typing import List, Dict


class TranscriptNormalizer:
    def normalize(self, turns: List[Dict]) -> List[Dict]:
        normalized_turns = []
        
        for i, turn in enumerate(turns):
            normalized_turn = {
                "turn_index": i,
                "speaker": self._normalize_speaker(turn.get("speaker", "unknown")),
                "text": self._normalize_text(turn.get("text", "")),
                "original_text": turn.get("text", ""),
                "start_ms": turn.get("start_ms", 0),
                "end_ms": turn.get("end_ms", 0),
                "confidence": turn.get("confidence", 0.0)
            }
            normalized_turns.append(normalized_turn)
        
        return normalized_turns
    
    def _normalize_speaker(self, speaker: str) -> str:
        speaker_mapping = {
            "doctor": "doctor",
            "patient": "patient",
            "unknown": "unknown",
            "spk0": "doctor",
            "spk1": "patient"
        }
        return speaker_mapping.get(speaker.lower(), "unknown")
    
    def _normalize_text(self, text: str) -> str:
        text = re.sub(r'\s+', '', text)
        text = self._normalize_punctuation(text)
        text = self._normalize_numbers(text)
        return text
    
    def _normalize_punctuation(self, text: str) -> str:
        punctuation_map = {
            ',': '，',
            '.': '。',
            '?': '？',
            '!': '！',
            ':': '：',
            ';': '；'
        }
        for en_punc, cn_punc in punctuation_map.items():
            text = text.replace(en_punc, cn_punc)
        return text
    
    def _normalize_numbers(self, text: str) -> str:
        return text
```

- [ ] **Step 2: 提交标准化模块**

```bash
git add backend/services/normalizer.py
git commit -m "feat: 添加转写结果标准化模块"
```

---

### Task 15: 创建ASR纠错规则文件

**Files:**
- Create: `config/asr_correction_rules.json`

- [ ] **Step 1: 创建纠错规则**

```json
{
    "medical_terms": {
        "阿莫西林": ["阿莫希林", "阿莫西灵", "阿莫希灵"],
        "头孢": ["头包", "投孢"],
        "青霉素": ["青梅素", "青梅速"],
        "布洛芬": ["布洛分", "不洛芬"],
        "对乙酰氨基酚": ["对乙先氨基酚", "对乙酰氨基分"],
        "阿司匹林": ["阿司匹灵", "阿斯匹林"],
        "胰岛素": ["胰导素", "一岛素"],
        "高血压": ["高血牙", "搞血压"],
        "糖尿病": ["堂尿病", "唐尿病"],
        "冠心病": ["观心病", "关心病"]
    },
    "pinyin_similar": {
        "头痛": ["头疼"],
        "发烧": ["发骚"],
        "咳嗽": ["刻嗽"],
        "恶心": ["偶心"],
        "腹泻": ["夫泻"]
    }
}
```

- [ ] **Step 2: 提交纠错规则**

```bash
git add config/asr_correction_rules.json
git commit -m "feat: 添加ASR纠错规则"
```

---

## 阶段3：前端优化

### Task 16: 创建结果展示页面

**Files:**
- Create: `frontend/result.html`
- Create: `frontend/js/result.js`

- [ ] **Step 1: 创建结果页面HTML**

```html
<!-- frontend/result.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>转写结果 - 中文门诊病历生成系统</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <h1>转写结果</h1>
        
        <div class="info-section">
            <p><strong>就诊记录:</strong> <span id="visitId"></span></p>
            <p><strong>状态:</strong> <span id="status"></span></p>
            <p><strong>音频时长:</strong> <span id="audioDuration"></span></p>
        </div>
        
        <div class="actions">
            <button id="startTranscribe" class="btn-primary">开始转写</button>
            <button id="refreshStatus" class="btn-secondary" style="display: none;">刷新状态</button>
        </div>
        
        <div class="turns-section" id="turnsSection" style="display: none;">
            <h2>转写结果</h2>
            <div id="turnsList"></div>
        </div>
        
        <div class="loading" id="loadingSection" style="display: none;">
            <p>正在转写中，请稍候...</p>
            <div class="progress-bar">
                <div class="progress-fill" id="progressFill"></div>
            </div>
        </div>
    </div>
    
    <script src="/static/js/result.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建结果页面JavaScript**

```javascript
// frontend/js/result.js
document.addEventListener('DOMContentLoaded', async function() {
    const urlParams = new URLSearchParams(window.location.search);
    const visitId = urlParams.get('visit_id');
    
    if (!visitId) {
        alert('缺少visit_id参数');
        return;
    }
    
    document.getElementById('visitId').textContent = visitId;
    
    const startBtn = document.getElementById('startTranscribe');
    const refreshBtn = document.getElementById('refreshStatus');
    const turnsSection = document.getElementById('turnsSection');
    const loadingSection = document.getElementById('loadingSection');
    
    await loadVisitInfo(visitId);
    
    startBtn.addEventListener('click', async () => {
        startBtn.disabled = true;
        loadingSection.style.display = 'block';
        
        try {
            const response = await fetch(`/api/asr/transcribe/${visitId}`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.success) {
                await pollTaskStatus(result.task_id, visitId);
            } else {
                throw new Error(result.message || '转写失败');
            }
        } catch (error) {
            alert('转写失败: ' + error.message);
            startBtn.disabled = false;
            loadingSection.style.display = 'none';
        }
    });
    
    refreshBtn.addEventListener('click', async () => {
        await loadTranscript(visitId);
    });
    
    async function loadVisitInfo(visitId) {
        try {
            const response = await fetch(`/api/transcript/${visitId}`);
            const result = await response.json();
            
            document.getElementById('status').textContent = getStatusText(result.status);
            document.getElementById('audioDuration').textContent = formatDuration(result.audio_duration);
            
            if (result.status === 'completed') {
                startBtn.style.display = 'none';
                await loadTranscript(visitId);
            } else if (result.status === 'processing') {
                startBtn.style.display = 'none';
                loadingSection.style.display = 'block';
            }
        } catch (error) {
            console.error('加载就诊信息失败:', error);
        }
    }
    
    async function pollTaskStatus(taskId, visitId) {
        const maxAttempts = 60;
        let attempts = 0;
        
        const poll = async () => {
            try {
                const response = await fetch(`/api/task/${taskId}`);
                const result = await response.json();
                
                if (result.status === 'completed') {
                    loadingSection.style.display = 'none';
                    await loadTranscript(visitId);
                    return;
                } else if (result.status === 'failed') {
                    throw new Error(result.error_message || '转写失败');
                }
                
                attempts++;
                if (attempts < maxAttempts) {
                    setTimeout(poll, 2000);
                } else {
                    throw new Error('转写超时');
                }
            } catch (error) {
                alert('转写失败: ' + error.message);
                startBtn.disabled = false;
                loadingSection.style.display = 'none';
            }
        };
        
        poll();
    }
    
    async function loadTranscript(visitId) {
        try {
            const response = await fetch(`/api/transcript/${visitId}`);
            const result = await response.json();
            
            turnsSection.style.display = 'block';
            const turnsList = document.getElementById('turnsList');
            turnsList.innerHTML = '';
            
            result.turns.forEach(turn => {
                const turnDiv = document.createElement('div');
                turnDiv.className = `turn-item ${turn.speaker}`;
                
                const speakerClass = turn.speaker === 'doctor' ? 'doctor-turn' : 'patient-turn';
                const speakerText = turn.speaker === 'doctor' ? '医生' : '患者';
                
                turnDiv.innerHTML = `
                    <div class="turn-header ${speakerClass}">
                        <span class="time">[${formatTime(turn.start_ms)} - ${formatTime(turn.end_ms)}]</span>
                        <span class="speaker">${speakerText}</span>
                    </div>
                    <div class="turn-text">${turn.text}</div>
                    <div class="turn-confidence">置信度: ${turn.confidence.toFixed(2)}</div>
                `;
                
                turnsList.appendChild(turnDiv);
            });
        } catch (error) {
            console.error('加载转写结果失败:', error);
        }
    }
    
    function getStatusText(status) {
        const statusMap = {
            'pending': '等待中',
            'processing': '处理中',
            'completed': '已完成',
            'failed': '失败'
        };
        return statusMap[status] || status;
    }
    
    function formatDuration(seconds) {
        if (!seconds) return '未知';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}分${secs}秒`;
    }
    
    function formatTime(ms) {
        const seconds = Math.floor(ms / 1000);
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
});
```

- [ ] **Step 3: 更新CSS样式**

```css
/* 添加到 frontend/css/style.css */

.info-section {
    background: #f9f9f9;
    padding: 20px;
    border-radius: 4px;
    margin-bottom: 20px;
}

.info-section p {
    margin: 10px 0;
}

.actions {
    margin: 20px 0;
}

.btn-secondary {
    width: 100%;
    padding: 14px;
    background-color: #2196F3;
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 16px;
    cursor: pointer;
    margin-top: 10px;
    transition: background-color 0.3s;
}

.btn-secondary:hover {
    background-color: #1976D2;
}

.turns-section {
    margin-top: 30px;
}

.turns-section h2 {
    margin-bottom: 20px;
    color: #333;
}

.turn-item {
    margin-bottom: 20px;
    padding: 15px;
    border-radius: 4px;
    background: white;
    border: 1px solid #e0e0e0;
}

.turn-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;
    padding: 5px 10px;
    border-radius: 4px;
    font-weight: 500;
}

.doctor-turn {
    background-color: #e3f2fd;
    color: #1976D2;
}

.patient-turn {
    background-color: #e8f5e9;
    color: #388E3C;
}

.turn-text {
    font-size: 16px;
    line-height: 1.6;
    margin: 10px 0;
}

.turn-confidence {
    font-size: 14px;
    color: #666;
}

.loading {
    text-align: center;
    padding: 40px;
}
```

- [ ] **Step 4: 提交结果页面**

```bash
git add frontend/result.html frontend/js/result.js
git commit -m "feat: 添加转写结果展示页面"
```

---

### Task 17: 测试和验证

**Files:**
- Test: 准备测试音频文件

- [ ] **Step 1: 启动服务测试**

```bash
# 激活虚拟环境
source venv/Scripts/activate  # Windows
# 或
source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python -c "from backend.database import init_db; init_db()"

# 启动服务
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: 访问前端测试**

```
打开浏览器访问: http://localhost:8000/
上传测试音频文件
查看转写结果
```

- [ ] **Step 3: 提交测试验证**

```bash
git add .
git commit -m "test: 完成M1里程碑测试验证"
```

---

## 完成标准

- [ ] 可以上传wav/mp3音频文件
- [ ] 数据库中能看到visit记录
- [ ] 音频文件能落盘到data/audio目录
- [ ] 可以调用ASR转写接口
- [ ] 转写结果能写入transcript_turns表
- [ ] 能区分医生和患者发言
- [ ] 常见医疗术语ASR错误能被纠正
- [ ] 转写结果格式统一
- [ ] 前端可以展示转写结果
- [ ] 医生患者发言有颜色区分

---

## 注意事项

1. **FunASR模型下载**：首次运行时会自动下载模型，需要等待
2. **音频格式**：建议使用16kHz采样率的wav文件
3. **说话人分离**：当前使用简单映射，后续可优化
4. **ASR纠错**：规则表可根据实际情况扩充
5. **数据库**：SQLite适合原型开发，后续可迁移到PostgreSQL
