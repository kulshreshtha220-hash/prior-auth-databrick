import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

# Local test defaults: no Databricks calls.
os.environ.setdefault("PA_AGENT_MODE", "mock")
os.environ.setdefault("PA_STATE_STORE", "memory")
os.environ.setdefault("PA_WRITE_DELTA", "false")
os.environ.setdefault("PA_USE_PROMPT_REGISTRY", "false")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

SAMPLE = {
    "patient_name": "John Smith",
    "patient_dob": "1958-03-15",
    "provider_npi": "1720180003",
    "diagnosis_codes": ["R91.1", "J18.9", "R05.9"],
    "procedure_codes": ["31628"],
    "clinical_notes": (
        "68-year-old male with a 1.8 cm spiculated RLL nodule, increased from 1.2 cm over 3 months; "
        "PET/CT SUV max 4.2. 40 pack-year smoking history. Completed 14-day amoxicillin-clavulanate "
        "with no resolution. Recommend transbronchial lung biopsy (CPT 31628) for tissue diagnosis."
    ),
    "insurance_id": "MCR-123456789A",
}
