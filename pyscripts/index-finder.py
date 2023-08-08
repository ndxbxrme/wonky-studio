import json
import os

language = 'en'

with open(f'./rendered/data/{language}/script-processed-wav.json') as f:
  script = json.loads(f.read())

last_index = 0
for l, line in enumerate(script):
  if len(line["occurrences"])==0:
    print(f'{l} **** {line["line"]}')
  for occ in line["occurrences"]:
    this_index = occ["index"][0]
    if this_index > last_index:
      if this_index < last_index + 150:
        line["first_index"] = this_index
        last_index = this_index
        print(f'{l} {last_index} {line["line"]}')
        break