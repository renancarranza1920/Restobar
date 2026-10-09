"""Install a pinned, checksum verified DTE preparation reference locally.

No tax documents, credentials or taxpayer information are sent. Normal HTTPS
certificate verification and inherited proxy settings remain enabled.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parent.parent


def install(destination):
    metadata = json.loads((ROOT / "app/schemas/dte-reference.json").read_text())
    if destination.is_file():
        if hashlib.sha256(destination.read_bytes()).hexdigest() == metadata["sha256"]:
            print("Referencia DTE instalada y checksum correcto.")
            return
        raise RuntimeError("La referencia existente no coincide. Revísala antes de reemplazarla.")
    with urllib.request.urlopen(metadata["download_url"], timeout=45) as response:
        content = response.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise RuntimeError("La descarga excede el tamaño permitido.")
    if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
        raise RuntimeError("Checksum incorrecto: no se instalará la referencia.")
    parsed = json.loads(content)
    if parsed["properties"]["identificacion"]["properties"]["version"]["const"] != 1:
        raise RuntimeError("Versión inesperada.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print("Referencia DTE v1 instalada y checksum verificado. Vigencia oficial pendiente.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path,
                        default=ROOT / "instance/dte-schemas/dte-fe-v1.json")
    args = parser.parse_args()
    try:
        install(args.destination.resolve())
    except Exception as error:
        parser.exit(1, f"No se pudo instalar la referencia DTE: {error}\n")
