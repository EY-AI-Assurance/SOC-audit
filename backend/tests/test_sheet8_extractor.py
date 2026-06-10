import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.extraction import CUECItem
from app.services.extractor import _dedupe_sheet8_cuecs, _prepare_sheet8_text


class Sheet8ExtractorTests(unittest.TestCase):
    def test_keeps_every_bullet_in_confirmed_cuec_column(self):
        text = """
[PDF Page 45 / Report Page 45]
| Control Objective | Complementary User Entity Controls |
| --- | --- |
| Access Management | \uf06e User identities are verified via provided contact information. Therefore, user: entities should implement relevant controls. \uf06e The access key should be appropriately protected and kept confidential. \uf06e U0ser entities should establish network security standards. |
"""

        _, cuecs = _prepare_sheet8_text(text)

        self.assertEqual(3, len(cuecs))
        self.assertTrue(cuecs[0].description.startswith("User identities are verified"))
        self.assertTrue(cuecs[1].description.startswith("The access key should"))
        self.assertTrue(cuecs[2].description.startswith("U0ser entities should"))
        self.assertTrue(all(item.objective_and_page == "Access Management Page 45" for item in cuecs))

    def test_removes_table_labels_and_page_number_noise(self):
        text = """
[PDF Page 44 / Report Page 44]
| Control Objective | Complementary User Entity Controls |
| --- | --- |
| Domain | Responsibilities of User Entities |
| Access Management | \uf06e 7 \uf06e - 8 2 \uf06e The access key should be appropriately protected. |
"""

        _, cuecs = _prepare_sheet8_text(text)

        self.assertEqual(1, len(cuecs))
        self.assertEqual(
            "The access key should be appropriately protected.",
            cuecs[0].description,
        )

    def test_deduplicates_only_highly_similar_items_under_same_objective(self):
        cuecs = [
            CUECItem(
                objective_and_page="Access Management Page 45",
                description=(
                    "User entities should ensure that proper security configuration is "
                    "in place to support the integrity of user authentication systems "
                    "and to prevent unauthorized access."
                ),
            ),
            CUECItem(
                objective_and_page="Access Management Page 45",
                description=(
                    "User entities should ensure proper security configuration is in "
                    "place to support the integrity of user authentication systems and "
                    "to prevent unauthorized access."
                ),
            ),
            CUECItem(
                objective_and_page="Data Security Page 45",
                description=(
                    "User entities should ensure proper security configuration is in "
                    "place to support the integrity of user authentication systems and "
                    "to prevent unauthorized access."
                ),
            ),
        ]

        deduped = _dedupe_sheet8_cuecs(cuecs)

        self.assertEqual(2, len(deduped))
        self.assertEqual("Access Management Page 45", deduped[0].objective_and_page)
        self.assertEqual("Data Security Page 45", deduped[1].objective_and_page)


if __name__ == "__main__":
    unittest.main()
