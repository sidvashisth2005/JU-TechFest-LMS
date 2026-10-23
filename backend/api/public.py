"""Public endpoints (no login): the free animal symptom checker.

Owners who don't use the rest of LMS can open /disease, pick their animal and its signs,
and get the likely diseases with what to do now. Nothing is stored.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ml.disease import kb

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/disease/kb")
def disease_kb(species: str) -> dict:
    """Signs to show for one species, grouped by body area, in all three languages."""
    if species not in kb.SPECIES:
        raise HTTPException(400, f"species must be one of {list(kb.SPECIES)}")
    data = kb.load()
    return {
        "species": species,
        "categories": data["categories"],
        "symptoms": [{k: s[k] for k in ("id", "cat", "name", "short", "detail")} for s in kb.symptoms_for(species)],
        "diseases": len(kb.diseases_for(species)),
    }


class Check(BaseModel):
    species: str
    symptoms: list[str] = Field(min_length=1, max_length=40)


@router.post("/disease/predict")
def disease_predict(body: Check) -> dict:
    try:
        return kb.predict(body.species, body.symptoms)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
