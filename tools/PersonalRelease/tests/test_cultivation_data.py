from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate_cultivation as generator
from release import write


class CultivationDataTests(unittest.TestCase):
    def fixture(self, root):
        data, resources = root / "data", root / "resource"
        character = {
            "name": "Test",
            "rarity": 3,
            "profession": "PIONEER",
            "phases": [
                {"maxLevel": 45, "evolveCost": []},
                {"maxLevel": 60, "evolveCost": [{"id": "3211", "count": 3}]},
            ],
            "allSkillLvlup": [{"lvlUpCost": [{"id": "3301", "count": 2}]}],
            "skills": [
                {"levelUpCostCond": [{"levelUpCost": [{"id": "3303", "count": 4}]}]}
            ],
        }
        write(
            data / "character_table.json",
            {"char_1": character, "char_2": {**character, "profession": "CASTER"}},
        )
        write(
            data / "gamedata_const.json",
            {
                "characterExpMap": [[100, 117, -1], [120, -1], [191, -1]],
                "characterUpgradeCostMap": [[30, 36, -1], [48, -1], [76, -1]],
                "evolveGoldCost": [[], [], [], [15000, 60000]],
            },
        )
        write(
            data / "item_table.json",
            {"expItems": {"2001": {"gainExp": 200}, "2004": {"gainExp": 2000}}},
        )
        write(
            data / "building_data.json",
            {
                "workshopFormulas": {
                    "material": {
                        "itemId": "30013",
                        "count": 1,
                        "formulaType": "F_EVOLVE",
                        "goldCost": 100,
                        "costs": [{"id": "30012", "count": 5}],
                    },
                    "conversion": {
                        "itemId": "3211",
                        "count": 2,
                        "formulaType": "F_EVOLVE",
                        "goldCost": 0,
                        "costs": [{"id": "3271", "count": 3}],
                    },
                }
            },
        )
        write(
            resources / "item_index.json",
            {
                "30013": {},
                "3211": {},
                "3213": {"formula": {"3212": 2, "32001": 1}},
            },
        )
        write(
            resources / "stages.json",
            [
                {
                    "code": stage,
                    "dropInfos": [{"itemId": item, "dropType": "NORMAL_DROP"}],
                }
                for item, stage in generator.SOURCES.items()
            ],
        )
        return data, resources

    def test_costs_and_level_index_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            data, resources = self.fixture(Path(temp))
            result = generator.generate(data, resources, "a" * 40)
        operator = result["operators_by_id"]["char_1"]
        self.assertEqual(operator["role"], "Pioneer")
        self.assertEqual(operator["rarity"], 4)
        self.assertEqual(operator["phases"][1]["gold_cost"], 15000)
        self.assertEqual(operator["phases"][1]["evolve_cost"], {"3211": 3})
        self.assertEqual(operator["skill_levels"][0], {"3301": 2})
        self.assertEqual(operator["mastery"][0][0], {"3303": 4})
        self.assertEqual(result["leveling"]["experience"][0], [100, 117])
        self.assertEqual(result["leveling"]["gold"][0], [30, 36])
        self.assertEqual(result["experience_items"]["2004"], 2000)

    def test_same_name_different_profession_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            result = generator.generate(*self.fixture(Path(temp)), "a" * 40)
        self.assertEqual(len(result["operators"]), 1)
        self.assertEqual(len(result["operators_by_id"]), 2)
        self.assertEqual(result["operators_by_id"]["char_2"]["role"], "Caster")

    def test_chip_conversion_not_a_one_output_recipe(self):
        with tempfile.TemporaryDirectory() as temp:
            result = generator.generate(*self.fixture(Path(temp)), "a" * 40)
        self.assertNotIn("3211", result["formulas"])
        self.assertEqual(result["formulas"]["3213"], {"3212": 2, "32001": 1})
        self.assertEqual(result["formulas"]["30013"], {"30012": 5})
        self.assertEqual(result["formula_gold"]["30013"], 100)

    def test_resource_change_invalidating_stage_blocks_release(self):
        with tempfile.TemporaryDirectory() as temp:
            data, resources = self.fixture(Path(temp))
            write(resources / "stages.json", [])
            with self.assertRaisesRegex(ValueError, "Unverified material source"):
                generator.generate(data, resources, "a" * 40)


if __name__ == "__main__":
    unittest.main()
