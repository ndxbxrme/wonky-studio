!pip install git+https://github.com/huggingface/transformers.git
!pip install glob
import glob
import os
import sys
import librosa
import torch
import json
from transformers import pipeline

from google.colab import drive
drive.mount('/content/gdrive')
root = '/content/gdrive/MyDrive/LanguageAdventure'
os.chdir(root)

language = 'en'
checkpoint = f"openai/whisper-medium.{language}"
alignment_heads = [[11, 4], [14, 1], [14, 12], [14, 14], [15, 4], [16, 0], [16, 4], [16, 9], [17, 12], [17, 14], [18, 7], [18, 10], [18, 15], [20, 0], [20, 3], [20, 9], [20, 14], [21, 12]]

if torch.cuda.is_available() and torch.cuda.device_count() > 0:
    print('using cuda')
    from transformers import (
        AutomaticSpeechRecognitionPipeline,
        WhisperForConditionalGeneration,
        WhisperProcessor,
    )
    model = WhisperForConditionalGeneration.from_pretrained(checkpoint).to("cuda").half()
    processor = WhisperProcessor.from_pretrained(checkpoint)
    pipe = AutomaticSpeechRecognitionPipeline(
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        batch_size=8,
        torch_dtype=torch.float16,
        device="cuda:0"
    )
else:
    print('using cpu')
    pipe = pipeline(model=checkpoint)
pipe.model.generation_config.alignment_heads = alignment_heads

def predict(audio_data, sr):
    audio_inputs = librosa.resample(audio_data, orig_sr=sr, target_sr=pipe.feature_extractor.sampling_rate)
    output = pipe(audio_inputs, chunk_length_s=30, stride_length_s=[4, 2], return_timestamps="word")
    return output

audio_files = [os.path.basename(path).replace('.wav', '') for path in glob.glob(f'./sources/audio/{language}/*.wav')]
for audio_file in audio_files:
  print("loading audio")
  audio_data, sr = librosa.load(f"./sources/audio/{language}/{audio_files[0]}.wav", mono=True)
  print("loaded")
  audio_length = len(audio_data)
  seg_length = 30 * sr
  seg_stride = 20 * sr
  seg_position = 0
  transcription_data = []
  while seg_position < audio_length:
      chunk = audio_data[seg_position:seg_position + seg_length]
      transcription = predict(chunk, sr)
      transcription["seg_position"] = seg_position
      transcription_data.append(transcription)
      seg_position += seg_stride
  with os.open(f'./rendered/data/en/{audio_file}-transcription.json', 'w', encoding='utf-8') as f:
      f.write(json.dumps(transcription_data))