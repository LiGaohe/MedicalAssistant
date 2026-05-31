from .turn_cleaning import TurnCleaningStage
from .direct_soap_generation import DirectSOAPGenerationStage
from .hallucination_check import HallucinationCheckStage
from .claim_verification import ClaimVerificationStage
from .field_revision import FieldRevisionStage

# DEPRECATED — 以下Stage类保留用于向后兼容，不再在新流水线中使用
from .fact_extraction import FactExtractionStage
from .fact_consolidation import FactConsolidationStage
from .soap_generation import SOAPGenerationStage
from .verification import VerificationStage
