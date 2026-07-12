import json


def _load_blackboard_items(blackboard_path):
    if not blackboard_path.exists():
        blackboard_path.parent.mkdir(parents=True, exist_ok=True)
        blackboard_path.touch()
        return {}

    items = {}
    with blackboard_path.open("r", encoding="utf8") as blackboard:
        for line in blackboard:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            items[item["community_id"]] = item
    return items


def _write_blackboard_items(blackboard_path, items):
    blackboard_path.parent.mkdir(parents=True, exist_ok=True)
    with blackboard_path.open("w", encoding="utf8") as blackboard:
        for item in items.values():
            blackboard.write(json.dumps(item) + "\n")
