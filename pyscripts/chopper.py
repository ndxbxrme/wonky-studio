import glob
import os
import librosa
import json
import re
import soundfile as sf
import traceback

language = 'en'

def clean_text(text):
  text = text.strip()
  text = re.sub(r'[^\w\s]', '', text)
  text = text.lower()
  text = re.sub(r'\s+', ' ', text)
  return text

with open(f'./rendered/data/{language}/script-processed.json', 'r', encoding='utf-8') as f:
  script = json.loads(f.read())
audio_files = [os.path.basename(path).replace('.wav', '') for path in glob.glob(f'./sources/audio/{language}/*.wav')]
audios = dict()
for filename in audio_files:
  audio, sr = librosa.load(f"./sources/audio/{language}/{filename}.wav")
  audios[filename] = audio
print('audio loaded')
for l, line in enumerate(script):
  print(l)
  if l == 818:
    continue
  try:
    if clean_text(line["line"]) == 'a':
      continue
    for occ in line["occurrences"]:
      mypath = f'./rendered/audio/{language}'
      for dir in line['path']:
        if '/' in dir:
          bits = dir.split('/')
          for bit in bits:
            mypath = mypath + '/' + bit.replace('*', '').strip()
            if not os.path.exists(mypath):
              os.mkdir(mypath)
        else:
          mypath = mypath + '/' + dir.replace('*', '')
          if not os.path.exists(mypath):
            os.mkdir(mypath)
      audio = audios[occ['file']]
      segment = audio[occ["start"]:occ["end"]]
      print(f"exporting {mypath}/{occ['path']}")
      occ["full_path"] = f"{mypath}/{occ['path']}"
      wavpath = f"{mypath}/{occ['path'].replace('.wav', '.ogg')}"
      yt, index = librosa.effects.trim(segment)
      sf.write(wavpath, yt, sr, format='ogg', subtype='vorbis')
  except Exception as e:
    print(f"goddamit: {e}")
    traceback.print_exc()

with open(f'./rendered/data/{language}/script-processed-wav.json', 'w', encoding='utf-8') as f:
  f.write(json.dumps(script))    