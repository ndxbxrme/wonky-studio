import os
import json
import shutil

with open('./rendered/data/en/game.json', 'r', encoding='utf-8') as f:
    game = json.loads(f.read())
with open('./sources/sources.json', 'r', encoding='utf-8') as f:
    sources = json.loads(f.read())

usedIds = []
for room in game["rooms"]:
    for object in room["objects"]:
        for state in object["states"]:
            for source in state["sources"]:
                usedIds.append(source["id"])
goodSources = []
for source in sources:
    if source["id"] in usedIds:
        goodSources.append(source)
    else:
        path_to_delete = source["path"]
        if os.path.exists(path_to_delete) and os.path.isdir(path_to_delete):
            print(f"deleting {path_to_delete}")
            shutil.rmtree(path_to_delete)


with open('./sources/sources.json', 'w', encoding='utf-8') as f:
    f.write(json.dumps(goodSources))