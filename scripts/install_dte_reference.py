"""Verify the bundled official MH schemas offline, with optional verified copy.

The source is the ZIP supplied by the user from factura.gob.sv. No remote
reference is downloaded, and no credentials or taxpayer data are required.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parent.parent


def install(destination=None):
    metadata = json.loads((ROOT / "app/schemas/dte-reference.json").read_text())
    for reference in metadata["schemas"].values():
        source = ROOT / "app/schemas" / reference["path"]
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != reference["sha256"]:
            raise RuntimeError(f"Checksum incorrecto en {source.name}.")
        Draft7Validator.check_schema(json.loads(content))
        if destination:
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / source.name
            if target.exists() and target.read_bytes() != content:
                raise RuntimeError(f"{target.name} ya existe y tiene otros bytes; revísalo antes de reemplazarlo.")
            if not target.exists():
                shutil.copyfile(source, target)
        print(f"{reference['name']} v{reference['version']}: esquema oficial incluido, SHA-256 correcto.")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, help="Directorio opcional para copiar los esquemas verificados.")
    args = parser.parse_args()
    try:
        install(args.destination.resolve() if args.destination else None)
    except Exception as error:
        parser.exit(1, f"No se pudo verificar la referencia DTE: {error}\n")
