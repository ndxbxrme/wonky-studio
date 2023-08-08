import os
import glob
import json

language = 'en'

audio_files = [os.path.basename(path).replace('.wav', '') for path in glob.glob(f'./sources/audio/{language}/*.wav')]

# Function to get all the indexes covered by the ranges
def get_covered_indexes(ranges_obj):
    covered_indexes = set()
    for item in ranges_obj:
        for r in item["occurrences"]:
            covered_indexes.update(range(r["index"][0], r["index"][1] + 1))
    return covered_indexes

# Function to convert a list of indexes to a list of ranges
def indexes_to_ranges(index_list):
    ranges = []
    start = None
    for i, idx in enumerate(index_list):
        if start is None:
            start = idx
        elif idx - index_list[i-1] != 1:
            ranges.append([start, index_list[i-1]])
            start = idx
    # Add the last range
    if start is not None:
        ranges.append([start, index_list[-1]])
    return ranges

with open(f'./rendered/data/{language}/script-processed-wav.json', 'r', encoding='utf-8') as f:
    script = json.loads(f.read())
with open(f'./rendered/data/{language}/words.json', 'r', encoding='utf-8') as f:
    words = json.loads(f.read())
# Get all the covered indexes from the ranges_object
covered_indexes_set = get_covered_indexes(script)
# Create a set of all possible indexes from 0 to 49
all_indexes_set = set(range(len(words)))
# Find the uncovered indexes
uncovered_indexes = all_indexes_set - covered_indexes_set
# Sort the uncovered indexes for better visualization
uncovered_indexes = sorted(list(uncovered_indexes))
# Convert the list of uncovered indexes to a list of ranges
uncovered_ranges = indexes_to_ranges(uncovered_indexes)
time_ranges = {
    "all": uncovered_ranges
}
for audio_file in audio_files:
  time_ranges[audio_file] = {
      "timestamps": [[words[range[0]]["timestamp"][0], words[range[1]]["timestamp"][1]] for range in uncovered_ranges if words[range[0]]["file"]==audio_file ],
      "indexes": [range for range in uncovered_ranges if words[range[0]]["file"]==audio_file ]
  }
with open(f'./rendered/data/{language}/time-ranges.json', 'w', encoding='utf-8') as f:
   f.write(json.dumps(time_ranges))