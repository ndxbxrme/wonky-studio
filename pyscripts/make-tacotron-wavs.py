import json
import string
import shutil
def convert_to_uppercase_no_punctuation(text):
    upper_text = text.upper()
    no_punctuation_text = upper_text.translate(str.maketrans("", "", string.punctuation))
    return no_punctuation_text
with open('./rendered/data/en/script-processed-wav.json', 'r', encoding='utf-8') as f:
    script = json.loads(f.read())
i = 0
list = []
for phrase in script:
    try:
      i += 1
      occ = phrase["occurrences"][0]
      text = convert_to_uppercase_no_punctuation(occ["text"])
      list.append(f"/content/TTS-TT2/wavs/{i}.wav|{text}")
      path = occ["full_path"]
      try:
          shutil.copy(path, f"tacotron/{i}.wav")
      except FileNotFoundError:
          print(f"Error: Source file '{path}' not found.")
      except PermissionError:
          print(f"Error: Permission denied while copying '{path}'.")
      except shutil.Error as e:
          print(f"Error copying '{path}': {e}")
    except (KeyError, IndexError):
      i -= 1
      pass
with open('./tacotron/list.txt', 'w', encoding='utf-8') as f:
   f.write('\n'.join(list))