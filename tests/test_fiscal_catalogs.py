"""Official MH catalog provenance, exact codes and territorial relationships."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.fiscal_catalogs import (
    DATASET_PATH, PROVENANCE_PATH, _dataset, catalog_label, catalog_metadata,
    catalog_options, district_options, municipality_options, validate_catalog_code,
)


class FiscalCatalogTests(unittest.TestCase):
    def test_import_covers_all_33_catalogs_and_preserves_source_provenance(self):
        raw = DATASET_PATH.read_bytes()
        dataset = json.loads(raw)
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(dataset["catalogs"]), {f"CAT-{number:03}" for number in range(1, 34)})
        self.assertEqual(sum(len(c["entries"]) for c in dataset["catalogs"].values()), 1681)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), provenance["dataset_sha256"])
        self.assertEqual(provenance["source_sha256"], "e86d7edc503d876564cd2bf9b251fb100f838199330c0c513048f4075669b2c6")
        self.assertEqual(catalog_metadata()["version"], "1.1")
        self.assertEqual(catalog_metadata()["workbook_modified_at"], "2026-06-29T20:30:20")
        self.assertIsNone(catalog_metadata()["effective_date"])
        for catalog in dataset["catalogs"].values():
            for entry in catalog["entries"]:
                self.assertIsInstance(entry["code"], str)
                self.assertGreater(entry["source_row"], 0)

    def test_exact_lookup_preserves_leading_zeroes_without_prefix_guesses(self):
        self.assertEqual(catalog_label("CAT019", "01111"), "Cultivo de cereales excepto arroz y para forrajes")
        self.assertEqual(catalog_label("CAT-019", "56101"), "Restaurantes")
        for wrong in ("1111", 1111, "011", "56101 ", "056101", "561", None, 56101.0, True):
            self.assertFalse(validate_catalog_code("CAT-019", wrong))
        self.assertTrue(validate_catalog_code("CAT-014", 59))
        self.assertEqual(catalog_label("CAT-014", 59), "Unidad")
        self.assertFalse(validate_catalog_code("CAT-014", "059"))
        self.assertFalse(validate_catalog_code("CAT-017", 1))
        self.assertFalse(validate_catalog_code("CAT-020", "sv"))
        self.assertEqual(catalog_label("CAT-028", "0000.000"), "Tránsito Aduanero")
        self.assertFalse(validate_catalog_code("CAT-028", "0000.0"))

    def test_official_payment_codes_distinguish_debit_credit_and_transfer(self):
        expected = {"01": "Billetes y monedas", "02": "Tarjeta Débito", "03": "Tarjeta Crédito",
                    "05": "Transferencia-Depósito Bancario", "11": "Bitcoin"}
        for code, label in expected.items():
            self.assertEqual(catalog_label("CAT-017", code), label)
        self.assertFalse(validate_catalog_code("CAT-017", "06"))
        self.assertEqual(catalog_label("CAT-022", "36"), "NIT")
        self.assertEqual(catalog_label("CAT-022", "13"), "DUI")
        self.assertEqual(catalog_label("CAT-022", "03"), "Pasaporte")
        self.assertEqual(catalog_label("CAT-022", "02"), "Carnet de Residente")

    def test_new_municipalities_are_not_legacy_district_codes(self):
        self.assertEqual(len(catalog_options("CAT-013")), 45)
        self.assertEqual(len(catalog_options("CAT-008")), 263)
        self.assertEqual([(e["code"], e["label"]) for e in municipality_options("06")], [
            ("20", "SAN SALVADOR NORTE"), ("21", "SAN SALVADOR OESTE"),
            ("22", "SAN SALVADOR ESTE"), ("23", "SAN SALVADOR CENTRO"), ("24", "SAN SALVADOR SUR"),
        ])
        self.assertEqual(catalog_label("CAT-013", "23", department="06"), "SAN SALVADOR CENTRO")
        self.assertEqual(catalog_label("CAT-013", "23", department="05"), "LA LIBERTAD NORTE")
        self.assertFalse(validate_catalog_code("CAT-013", "23"))
        self.assertFalse(validate_catalog_code("CAT-013", "14", department="06"))
        self.assertTrue(validate_catalog_code("CAT-008", "14", department="06"))
        self.assertEqual(catalog_label("CAT-008", "14", department="06"), "SAN SALVADOR")
        self.assertEqual(municipality_options("6"), [])
        self.assertEqual(municipality_options("99"), [])
        self.assertEqual(municipality_options(None), [])
        self.assertEqual(len(municipality_options("00")), 1)
        self.assertFalse(validate_catalog_code("CAT-013", "00", department="06"))

    def test_district_codes_repeating_between_departments_keep_parent(self):
        self.assertEqual(catalog_label("CAT-008", "01", department="01"), "AHUACHAPÁN")
        self.assertEqual(catalog_label("CAT-008", "01", department="02"), "CANDELARIA DE LA FRONTERA")
        self.assertIsNone(catalog_label("CAT-008", "01"))
        self.assertFalse(validate_catalog_code("CAT-008", "20", department="06"))
        self.assertTrue(validate_catalog_code("CAT-008", "20", department="12"))
        self.assertEqual([len(district_options(f"{number:02}")) for number in range(1, 15)],
                         [12, 13, 16, 33, 22, 19, 16, 22, 9, 13, 23, 20, 26, 18])
        self.assertEqual([len(municipality_options(f"{number:02}")) for number in range(1, 15)],
                         [3, 4, 4, 3, 6, 5, 2, 3, 2, 2, 3, 3, 2, 2])

    def test_tax_codes_retain_distinct_application_groups(self):
        repeated = [entry for entry in catalog_options("CAT-015") if entry["code"] == "D4"]
        self.assertEqual(len(repeated), 2)
        self.assertNotEqual(repeated[0]["group"], repeated[1]["group"])
        self.assertEqual(catalog_label("CAT-015", "D4"), "Otros impuestos casos especiales")
        self.assertEqual(catalog_label("CAT-015", "20"), "Impuesto al Valor Agregado 13%")

    def test_returned_data_cannot_mutate_the_cached_catalog(self):
        options = catalog_options("CAT-017")
        options[0]["label"] = "modified"
        options.clear()
        self.assertEqual(catalog_label("CAT-017", "01"), "Billetes y monedas")
        metadata = catalog_metadata()
        metadata["version"] = "modified"
        self.assertEqual(catalog_metadata()["version"], "1.1")

    def test_invalid_catalog_ids_fail_explicitly(self):
        for invalid in ("CAT17", "CAT-999", "foo", None):
            with self.assertRaises(ValueError):
                catalog_options(invalid)

    def test_dataset_checksum_rejects_modified_content(self):
        with TemporaryDirectory(prefix="restobar-catalog-integrity-") as scratch:
            tampered = Path(scratch) / "mh-catalogs.json"
            tampered.write_bytes(DATASET_PATH.read_bytes() + b" ")
            _dataset.cache_clear()
            try:
                with patch("app.fiscal_catalogs.DATASET_PATH", tampered):
                    with self.assertRaisesRegex(RuntimeError, "checksum"):
                        catalog_options("CAT-017")
            finally:
                _dataset.cache_clear()


if __name__ == "__main__":
    unittest.main()
