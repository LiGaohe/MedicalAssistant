import pytest
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database import Base
from backend.models.transcript import TranscriptTurn
from backend.models.evidence import EvidenceSpan
from backend.models.visit import Visit
from backend.services.evidence_service import EvidenceService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def evidence_service(db_session):
    with patch.object(EvidenceService, '_load_triggers') as mock_load:
        mock_load.return_value = {
            "chief_complaint": {
                "triggers": ["头痛", "头晕", "不舒服"],
                "speaker_preference": "patient",
                "weight": 1.0
            },
            "diagnosis": {
                "triggers": ["诊断", "考虑", "可能是"],
                "speaker_preference": "doctor",
                "weight": 1.2
            }
        }
        service = EvidenceService(db_session)
        return service


class TestTranscriptTurnConfidence:
    """测试 TranscriptTurn 模型的置信度字段"""
    
    def test_create_turn_with_confidence(self, db_session):
        visit = Visit(visit_id="test_visit_001", audio_path="test.wav")
        db_session.add(visit)
        db_session.commit()
        
        turn = TranscriptTurn(
            visit_id="test_visit_001",
            turn_index=0,
            speaker="patient",
            text="我最近头痛",
            start_ms=0,
            end_ms=2000,
            confidence=0.85
        )
        db_session.add(turn)
        db_session.commit()
        
        saved_turn = db_session.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == "test_visit_001"
        ).first()
        
        assert saved_turn.confidence == 0.85
    
    def test_create_turn_without_confidence(self, db_session):
        visit = Visit(visit_id="test_visit_002", audio_path="test.wav")
        db_session.add(visit)
        db_session.commit()
        
        turn = TranscriptTurn(
            visit_id="test_visit_002",
            turn_index=0,
            speaker="doctor",
            text="请问哪里不舒服",
            start_ms=0,
            end_ms=1500
        )
        db_session.add(turn)
        db_session.commit()
        
        saved_turn = db_session.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == "test_visit_002"
        ).first()
        
        assert saved_turn.confidence == 1.0


class TestEvidenceServiceConfidence:
    """测试证据选择服务的置信度过滤功能"""
    
    def test_filter_low_confidence_turns(self, evidence_service, db_session):
        visit = Visit(visit_id="test_visit_003", audio_path="test.wav")
        db_session.add(visit)
        db_session.commit()
        
        turns = [
            TranscriptTurn(
                visit_id="test_visit_003",
                turn_index=0,
                speaker="patient",
                text="我最近头痛",
                start_ms=0,
                end_ms=2000,
                confidence=0.9
            ),
            TranscriptTurn(
                visit_id="test_visit_003",
                turn_index=1,
                speaker="doctor",
                text="诊断是偏头痛",
                start_ms=2000,
                end_ms=4000,
                confidence=0.3
            ),
        ]
        for turn in turns:
            db_session.add(turn)
        db_session.commit()
        
        evidence = evidence_service.select_evidence_by_rules(
            "test_visit_003",
            confidence_threshold=0.5
        )
        
        for e in evidence:
            assert e.confidence >= 0.5
    
    def test_confidence_affects_score(self, evidence_service, db_session):
        visit = Visit(visit_id="test_visit_004", audio_path="test.wav")
        db_session.add(visit)
        db_session.commit()
        
        turn_high = TranscriptTurn(
            visit_id="test_visit_004",
            turn_index=0,
            speaker="patient",
            text="我最近头痛",
            start_ms=0,
            end_ms=2000,
            confidence=0.9
        )
        turn_low = TranscriptTurn(
            visit_id="test_visit_004",
            turn_index=1,
            speaker="patient",
            text="我最近头痛头晕",
            start_ms=2000,
            end_ms=4000,
            confidence=0.6
        )
        
        db_session.add_all([turn_high, turn_low])
        db_session.commit()
        
        score_high = evidence_service._calculate_turn_score(
            turn_high,
            ["头痛"],
            "patient",
            1.0,
            confidence_threshold=0.5
        )
        score_low = evidence_service._calculate_turn_score(
            turn_low,
            ["头痛"],
            "patient",
            1.0,
            confidence_threshold=0.5
        )
        
        assert score_high > score_low
    
    def test_zero_confidence_turn_filtered(self, evidence_service, db_session):
        visit = Visit(visit_id="test_visit_005", audio_path="test.wav")
        db_session.add(visit)
        db_session.commit()
        
        turn = TranscriptTurn(
            visit_id="test_visit_005",
            turn_index=0,
            speaker="patient",
            text="我最近头痛",
            start_ms=0,
            end_ms=2000,
            confidence=0.3
        )
        db_session.add(turn)
        db_session.commit()
        
        score = evidence_service._calculate_turn_score(
            turn,
            ["头痛"],
            "patient",
            1.0,
            confidence_threshold=0.5
        )
        
        assert score == 0.0
    
    def test_evidence_inherits_turn_confidence(self, evidence_service, db_session):
        visit = Visit(visit_id="test_visit_006", audio_path="test.wav")
        db_session.add(visit)
        db_session.commit()
        
        turn = TranscriptTurn(
            visit_id="test_visit_006",
            turn_index=0,
            speaker="patient",
            text="我最近头痛",
            start_ms=0,
            end_ms=2000,
            confidence=0.85
        )
        db_session.add(turn)
        db_session.commit()
        
        evidence = evidence_service.select_evidence_by_rules(
            "test_visit_006",
            confidence_threshold=0.5
        )
        
        if evidence:
            assert evidence[0].confidence == 0.85


class TestASRServiceConfidence:
    """测试 ASR 服务的置信度传递"""
    
    def test_funasr_turns_include_confidence(self):
        from backend.services.asr_service import ASRService
        
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "测试文本"
        mock_result.segments = []
        mock_result.speaker_segments = [
            {
                "speaker": "spk0",
                "text": "你好",
                "start_ms": 0,
                "end_ms": 1000,
                "confidence": 0.92
            }
        ]
        mock_result.duration_seconds = 1.0
        mock_result.inference_time = 0.5
        mock_engine.transcribe.return_value = mock_result
        
        service = ASRService({"engine_type": "funasr"})
        service.engine = mock_engine
        service.postprocessor = None
        
        result = service._transcribe_funasr_with_diarization("test.wav")
        
        assert "confidence" in result["turns"][0]
        assert result["turns"][0]["confidence"] == 0.92
    
    def test_qwen3_asr_turns_include_default_confidence(self):
        from backend.services.asr_service import ASRService
        
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "测试文本"
        mock_result.segments = [
            {"text": "你好", "start": 0, "end": 1000}
        ]
        mock_result.duration_seconds = 1.0
        mock_result.inference_time = 0.5
        mock_engine._get_audio_duration.return_value = 1.0
        mock_engine.transcribe.return_value = mock_result
        
        service = ASRService({"engine_type": "qwen3-asr"})
        service.engine = mock_engine
        
        result = service._transcribe_qwen3_asr("test.wav")
        
        assert "confidence" in result["turns"][0]
        assert result["turns"][0]["confidence"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
