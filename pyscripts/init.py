import os
import json

os.mkdir('./rendered')
os.mkdir('./rendered/audio')
os.mkdir('./rendered/audio/en')
os.mkdir('./rendered/data')
os.mkdir('./rendered/data/en')
os.mkdir('./sources')
os.mkdir('./sources/audio')
os.mkdir('./sources/audio/en')
os.mkdir('./sources/data')
os.mkdir('./sources/data/en')
os.mkdir('./sources/visual')
os.mkdir('./sources/visual/en')
os.mkdir('./upload-temp')

sources = []
game = {
    "rooms": []
}
script = []
with open('./rendered/data/en/game.json', 'w', encoding='utf-8') as f:
    f.write(json.dumps(game))
with open('./sources/data/en/script.json', 'w', encoding='utf-8') as f:
    f.write(json.dumps(script))
with open('./rendered/data/en/script-processed-wav.json', 'w', encoding='utf-8') as f:
    f.write(json.dumps(script))
with open('./sources/sources.json', 'w', encoding='utf-8') as f:
    f.write(json.dumps(sources))