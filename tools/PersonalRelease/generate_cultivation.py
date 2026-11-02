"""Generate the small, versioned cultivation database from MAA's game-data source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROLES = {
    "PIONEER": "Pioneer",
    "WARRIOR": "Warrior",
    "SNIPER": "Sniper",
    "CASTER": "Caster",
    "TANK": "Tank",
    "MEDIC": "Medic",
    "SUPPORT": "Support",
    "SPECIAL": "Special",
}

# These are explicit permanent sources, not an efficiency optimiser. Every ordinary
# material mapping is checked against the bundled NORMAL_DROP stage data below.
SOURCES = {
    "4001": "CE-6",
    "4006": "AP-5",
    "2001": "LS-6",
    "2002": "LS-6",
    "2003": "LS-6",
    "2004": "LS-6",
    "3301": "CA-5",
    "3302": "CA-5",
    "3303": "CA-5",
    "30011": "0-9",
    "30012": "1-7",
    "30021": "0-7",
    "30022": "2-2",
    "30023": "4-2",
    "30031": "0-11",
    "30032": "1-8",
    "30033": "3-8",
    "30041": "1-3",
    "30042": "2-1",
    "30043": "5-5",
    "30051": "1-6",
    "30052": "3-7",
    "30053": "4-5",
    "30061": "1-5",
    "30062": "1-12",
    "30063": "4-10",
    "30073": "4-4",
    "30083": "4-7",
    "30093": "4-8",
    "30103": "4-9",
    "31013": "7-8",
    "31023": "6-12",
    "31033": "R8-11",
    "31043": "9-4",
    "31053": "9-6",
    "31063": "11-3",
    "31073": "13-5",
    "31083": "13-15",
    "31093": "15-9",
    "31103": "17-5",
    "31113": "17-11",
}
for _item, _stage in {
    "321": "C",
    "322": "D",
    "323": "A",
    "324": "B",
    "325": "B",
    "326": "A",
    "327": "C",
    "328": "D",
}.items():
    for _tier in (1, 2):
        SOURCES[f"{_item}{_tier}"] = f"PR-{_stage}-{_tier}"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def cost(items) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items or []:
        count = item["count"]
        if not isinstance(count, int) or count < 0:
            raise ValueError(f"Invalid material count: {item!r}")
        if count:
            result[item["id"]] = result.get(item["id"], 0) + count
    return result


def rarity_index(value) -> int:
    return (
        int(value.removeprefix("TIER_")) - 1 if isinstance(value, str) else int(value)
    )


def generate(data: Path, resources: Path, source_commit: str) -> dict:
    characters = read(data / "character_table.json")
    constants = read(data / "gamedata_const.json")
    buildings = read(data / "building_data.json")
    items = read(data / "item_table.json")
    stages = read(resources / "stages.json")
    item_index = read(resources / "item_index.json")
    sources = dict(SOURCES)
    normal_drops = {
        (stage["code"], drop["itemId"])
        for stage in stages
        for drop in stage.get("dropInfos", [])
        if drop.get("dropType") == "NORMAL_DROP" and drop.get("itemId")
    }
    for item, stage in sources.items():
        if item.startswith(("300", "301", "310", "3110", "3111")):
            if (stage, item) not in normal_drops:
                raise ValueError(f"Unverified material source: {item} -> {stage}")

    operators = {}
    operators_by_id = {}
    for char_id, char in sorted(characters.items()):
        if not char_id.startswith("char_") or char.get("profession") not in ROLES:
            continue
        rarity = rarity_index(char["rarity"])
        phases = []
        for index, phase in enumerate(char["phases"]):
            gold = 0 if index == 0 else constants["evolveGoldCost"][rarity][index - 1]
            if gold < 0:
                raise ValueError(f"Missing promotion price: {char_id}, phase {index}")
            phases.append(
                {
                    "max_level": phase["maxLevel"],
                    "evolve_cost": cost(phase.get("evolveCost")),
                    "gold_cost": gold,
                }
            )
        role = ROLES[char["profession"]]
        operator = {
            "id": char_id,
            "name": char["name"],
            "rarity": rarity + 1,
            "role": role,
            "phases": phases,
            "skill_levels": [
                cost(x.get("lvlUpCost")) for x in char.get("allSkillLvlup", [])
            ],
            "mastery": [
                [cost(x.get("levelUpCost")) for x in skill.get("levelUpCostCond", [])]
                for skill in char.get("skills", [])
            ],
        }
        operators_by_id[char_id] = operator
        operators.setdefault(char["name"], operator)

    formulas = {}
    formula_gold = {}
    for formula in buildings["workshopFormulas"].values():
        item = formula["itemId"]
        # Chip conversion produces two chips from three of the other profession.
        # Exclude it instead of creating cyclic/incorrect one-output recipes.
        if formula["count"] != 1 or item not in item_index:
            continue
        if formula.get("formulaType") not in ("F_EVOLVE", "F_SKILL"):
            continue
        formulas[item] = cost(formula["costs"])
        formula_gold[item] = formula.get("goldCost", 0)
    for item, info in item_index.items():
        if item.startswith("32") and item.endswith("3") and info.get("formula"):
            formulas[item] = info["formula"]
            formula_gold[item] = 0

    experience = [[x for x in row if x >= 0] for row in constants["characterExpMap"]]
    gold = [[x for x in row if x >= 0] for row in constants["characterUpgradeCostMap"]]
    if len(experience) != 3 or any(len(a) != len(b) for a, b in zip(experience, gold)):
        raise ValueError("Unexpected leveling data shape")
    return {
        "schema_version": 1,
        "source_commit": source_commit,
        "operators": operators,
        "operators_by_id": operators_by_id,
        "leveling": {"experience": experience, "gold": gold},
        "experience_items": {
            key: value["gainExp"] for key, value in items["expItems"].items()
        },
        "sources": sources,
        "formulas": formulas,
        "formula_gold": formula_gold,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--resources", default="resource", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--output", default="personal/resource/cultivation.json", type=Path
    )
    args = parser.parse_args()
    result = generate(args.data, args.resources, args.source_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )
    print(
        f"Generated {len(result['operators'])} operators and {len(result['formulas'])} recipes"
    )


if __name__ == "__main__":
    main()
