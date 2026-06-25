"""citation_gate — verify bibliographic citations against scholarly sources."""
from .models import Verdict, Citation, CanonicalRecord, CitationResult

__all__ = ["Verdict", "Citation", "CanonicalRecord", "CitationResult"]
