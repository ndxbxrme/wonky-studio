import re
import json
from transformers import pipeline

languages = [
  { "code": "es", "language": "Spanish" },
  { "code": "fr", "language": "French" },
  { "code": "pt", "language": "Portuguese", "roa": "por" },
  { "code": "de", "language": "German" },
  { "code": "it", "language": "Italian" },
  { "code": "nl", "language": "Dutch" },
  { "code": "sv", "language": "Swedish" },
  { "code": "da", "language": "Danish" },
  { "code": "nor", "language": "Norwegian" },
  { "code": "fi", "language": "Finnish"},
  { "code": "pol", "language": "Polish" },
  { "code": "ro", "language": "Romanian" },
  { "code": "tur", "language": "Turkish" },
  { "code": "hu", "language": "Hungarian" },
  { "code": "cs", "language": "Czech" },
  { "code": "sk", "language": "Slovak" },
  { "code": "hrv", "language": "Croatian" },
  { "code": "srp", "language": "Serbian" },
  { "code": "slk", "language": "Slovene" }
]
with open("./rendered/data/en/script-processed-wav.json", "r", encoding="utf-8") as f:
    script = json.loads(f.read())
for language in languages:
    try:
      code = language['code']
      roa = language.get('roa')
      if roa:
          code = 'roa'
      model = f"Helsinki-NLP/opus-mt-en-{code}"
      task = pipeline(
          "translation",
          model=model,
          tokenizer=model
      )
      for l, phrase in enumerate(script):
        input_text = phrase["line"]
        if roa:
            input_text = f'>>{roa}<< {input_text}'
        phrase["autotrans"] = phrase.get("autotrans") or {}


        text_to_translate = re.split('(?<=[.!?]) +', input_text)
        for i, text in enumerate(text_to_translate):
            translation = task(text)
            text_to_translate[i] = translation[0]["translation_text"]
        translated = ' '.join(text_to_translate)
        phrase["autotrans"][language['code']] = {
            "text": translated
        }
        print(f"{language['code']} {l}/{len(script)} {phrase['line']}")
    except:
        print(f"bad language: {language['language']}")

with open("./rendered/data/en/script-processed-wav.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(script))
print(script[0])