"""Local, exact lookups for MH catalogs from the supplied official workbook.

Codes remain text, including leading zeroes. Catalog identifiers allow CAT017
or CAT-017; values never use prefix, case-insensitive or zero-padding matches.
Territorial codes require their department because codes repeat between it.
"""

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re


DATASET_PATH = Path(__file__).parent / "schemas/mh-catalogs.json"
PROVENANCE_PATH = DATASET_PATH.with_name("mh-catalogs-provenance.json")
TERRITORIAL_CATALOGS = {"CAT-008", "CAT-013"}


@lru_cache(maxsize=1)
def _dataset():
    encoded = DATASET_PATH.read_bytes()
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    if hashlib.sha256(encoded).hexdigest() != provenance.get("dataset_sha256"):
        raise RuntimeError("El catálogo de Hacienda no coincide con su checksum. Revisa la instalación.")
    dataset = json.loads(encoded)
    if dataset["metadata"]["source_sha256"] != provenance.get("source_sha256"):
        raise RuntimeError("La procedencia del catálogo de Hacienda no coincide. Revisa la instalación.")
    return dataset


def _catalog_id(catalog_id):
    match = re.fullmatch(r"CAT-?(\d{3})", str(catalog_id).upper())
    if not match:
        raise ValueError(f"Identificador de catálogo inválido: {catalog_id!r}.")
    result = "CAT-" + match.group(1)
    if result not in _dataset()["catalogs"]:
        raise ValueError(f"Catálogo no disponible: {result}.")
    return result


def _code(code):
    if isinstance(code, str):
        return code
    if isinstance(code, int) and not isinstance(code, bool):
        return str(code)
    return None


def catalog_metadata():
    """Return source version, SHA-256 and file dates (not legal validity)."""
    return deepcopy(_dataset()["metadata"])


def catalog_options(catalog_id):
    """Return independent entry dicts with code, label and source_row.

    CAT-008 and CAT-013 also include department; CAT-015/019 retain source group.
    Repeated tax codes in CAT-015 represent different document locations, so
    their group is retained rather than silently discarded.
    """
    return deepcopy(_dataset()["catalogs"][_catalog_id(catalog_id)]["entries"])


def _matches(catalog_id, code, department):
    catalog_id = _catalog_id(catalog_id)
    code = _code(code)
    if code is None:
        return []
    if catalog_id in TERRITORIAL_CATALOGS:
        department = _code(department)
        if department is None:
            return []
    elif department is not None:
        # A department filter must never hide a caller selecting the wrong
        # catalog for address validation.
        return []
    return [entry for entry in _dataset()["catalogs"][catalog_id]["entries"]
            if entry["code"] == code and
            (catalog_id not in TERRITORIAL_CATALOGS or entry["department"] == department)]


def catalog_label(catalog_id, code, *, department=None):
    """Return the exact official label, or None for unknown/ambiguous codes."""
    labels = {entry["label"] for entry in _matches(catalog_id, code, department)}
    return next(iter(labels)) if len(labels) == 1 else None


def validate_catalog_code(catalog_id, code, *, department=None):
    """Whether a full code exists; territorial codes require department."""
    return bool(_matches(catalog_id, code, department))


def municipality_options(department):
    """Return CAT-013 municipalities for one exact department code."""
    code = _code(department)
    return [entry for entry in catalog_options("CAT-013") if entry["department"] == code]


def district_options(department):
    """Return CAT-008 districts grouped by department in the source workbook.

    The XLSX does not specify each district's municipality. Do not infer that
    relationship from overlapping codes or assume municipality equals district.
    """
    code = _code(department)
    return [entry for entry in catalog_options("CAT-008") if entry["department"] == code]
