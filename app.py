import falcon
import os
import re
import json
import librosa
import glob
import asyncio
import base64
import uuid
import string
import cv2
import torch
import rawpy
import numpy as np
import tifffile as tiff
import soundfile as sf
from functools import partial
from pydub import AudioSegment
from PIL import Image
from segment_anything import sam_model_registry, SamPredictor

sam_checkpoint = "sam_vit_h_4b8939.pth"
model_type = "vit_h"
device = "cuda"
sam = sam_model_registry[model_type](checkpoint=sam_checkpoint)
sam.to(device=device)
predictor = SamPredictor(sam)

def clean_text(text):
  text = text.strip()
  text = re.sub(r'[^\w\s]', '', text)
  text = text.lower()
  text = re.sub(r'\s+', ' ', text)
  return text

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

def sanitize_filename(filename):
    # Define a set of allowed characters for the filename (alphanumeric, underscore, dot, and hyphen)
    allowed_chars = set(string.ascii_letters + string.digits + '_-.')
    # Remove any unsafe characters from the filename and replace with underscores
    sanitized_filename = ''.join(c if c in allowed_chars else '_' for c in filename)
    return sanitized_filename

def generate_unique_filename():
    # Generate a UUID
    unique_id = uuid.uuid4()
    # Extract the first 8 characters from the UUID and convert to lowercase
    unique_string = str(unique_id)[:8].lower()
    return unique_string

def get_filename_without_extension(file_path):
    base_filename, _ = os.path.splitext(os.path.basename(file_path))
    return base_filename

def process_audio(temp_path, file_name, id, language):
    audio = AudioSegment.from_file(temp_path)
    mypath = f'sources/audio/{language}/{id}'
    if not os.path.exists(mypath):
        os.mkdir(mypath)
    # Save as .wav file
    audio.export(f'{mypath}/{file_name}.wav', format='wav')
    # Save as .ogg file
    audio.export(f'{mypath}/{file_name}.ogg', format='ogg')
    return mypath

def process_video(temp_path, id):
    mypath = f'sources/visual/{id}'
    if not os.path.exists(mypath):
        os.mkdir(mypath)
    video_capture = cv2.VideoCapture(temp_path)
    frame_count = 0
    while True:
        ret, frame = video_capture.read()
        if not ret:
            break
        # Save each frame as a .png file
        cv2.imwrite(f'{mypath}/frame_{frame_count:04d}.png', frame)
        frame_count += 1
    video_capture.release()
    return mypath

def process_image(temp_path, file_name, id):
    mypath = f'sources/visual/{id}'
    if not os.path.exists(mypath):
        os.mkdir(mypath)

    # Determine the file type (e.g., .jpg, .jpeg, .png, .dng, .tif) based on the file extension
    file_extension = temp_path.split('.')[-1].lower()

    if file_extension in ('jpg', 'jpeg', 'png'):
        # Convert common image formats to .png
        img = Image.open(temp_path)
        img.save(f'{mypath}/{file_name}.png')
    elif file_extension == 'dng':
        # Process .dng files using rawpy and convert to .png
        with rawpy.imread(temp_path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)

            # Save the .png file
            img = Image.fromarray(rgb)
            img.save(f'{mypath}/{file_name}.png')
    elif file_extension == 'tif':
        # Convert .tif file to .png
        tif_data = tiff.imread(temp_path)
        img = Image.fromarray(tif_data)
        img.save(f'{mypath}/{file_name}.png')

    return mypath

def save_mask_as_bw(mask, path, ext):
    # Create a 4-channel image with the same dimensions as the mask
    mask_rgba = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)

    # Set the RGB values based on the black and white mask
    mask_rgba[:, :, 0] = (mask * 255).astype(np.uint8)
    mask_rgba[:, :, 1] = (mask * 255).astype(np.uint8)
    mask_rgba[:, :, 2] = (mask * 255).astype(np.uint8)
    mask_rgba[:, :, 3] = (mask * 255).astype(np.uint8)

    # Save the image with the alpha channel
    cv2.imwrite(path.replace('.png', ext), mask_rgba)

def expand_and_blur_mask(mask, expansion_pixels, blur_kernel_size):
    # Convert mask to uint8 and create a binary mask
    mask = (mask * 255).astype(np.uint8)
    binary_mask = cv2.threshold(mask, 128, 255, cv2.THRESH_BINARY)[1]

    # Perform dilation to expand the mask
    kernel = np.ones((expansion_pixels, expansion_pixels), np.uint8)
    dilated_mask = cv2.dilate(binary_mask, kernel, iterations=1)

    # Apply Gaussian blur to the expanded mask
    blurred_mask = cv2.GaussianBlur(dilated_mask, (blur_kernel_size, blur_kernel_size), 0)

    # Convert the mask back to float in the range [0, 1]
    expanded_blurred_mask = blurred_mask.astype(np.float32) / 255.0

    return expanded_blurred_mask

def fill_mask_outlines(mask, fill_value):
    # Convert mask to uint8 and create a binary mask
    mask = (mask * 255).astype(np.uint8)
    binary_mask = cv2.threshold(mask, 128, 255, cv2.THRESH_BINARY)[1]

    # Find contours in the binary mask
    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Initialize a copy of the mask to store the filled regions
    filled_mask = np.zeros_like(mask)

    # Iterate through each contour
    for contour in contours:
        # Perform flood fill on the contour
        cv2.drawContours(filled_mask, [contour], -1, fill_value, thickness=cv2.FILLED)

    return filled_mask

class ErrorHandler:
    def __init__(self):
        pass

    def __call__(self, ex, req, resp, params):
        # Serve index.html for all errors
        print(ex)
        resp.status = falcon.HTTP_200
        resp.content_type = 'text/html'
        with open('index.html', 'r') as file:
            resp.body = file.read()

class GetAudioSourcesResource(object):
    def on_post(self, req, resp):
        doc = req.media
        language = doc.get("language") or "en"
        resp.status = falcon.HTTP_200
        resp.media = glob.glob(f'./sources/audio/{language}/*.ogg')
class AssignWordsResource(object):
    async def on_post(self, req, resp):
        doc = req.media
        language = doc.get("language") or "en"
        wordRange = doc["wordRange"]
        lineIndex = doc["lineIndex"]
        with open(f'./rendered/data/{language}/words.json', 'r', encoding='utf-8') as f:
            words = json.loads(f.read())
        with open(f'./rendered/data/{language}/script-processed-wav.json', 'r', encoding='utf-8') as f:
            script = json.loads(f.read())
        with open(f'./rendered/data/{language}/time-ranges.json', 'r', encoding='utf-8') as f:
            time_ranges = json.loads(f.read())
        start_word = words[wordRange[0]]
        end_word = words[wordRange[1]]
        phrase = script[lineIndex]
        words_joined = re.sub(r'\s+', ' ', " ".join(word["text"] for word in words[wordRange[0]:wordRange[1]])).strip()
        if end_word['timestamp'][1]:
          occ = {
            "text": words_joined,
            "start": int(start_word["timestamp"][0]),
            "end": int(end_word["timestamp"][1]),
            "path": f'{lineIndex:04}_{wordRange[0]:05}_{clean_text(words_joined).replace(" ", "_")[:50]}.wav',
            "file": start_word["file"],
            "index": wordRange,
            "edited": True
          }
          phrase["occurrences"].append(occ)


          audio_files = [os.path.basename(path).replace('.wav', '') for path in glob.glob(f'./sources/audio/{language}/*.wav')]
          covered_indexes_set = get_covered_indexes(script)
          all_indexes_set = set(range(len(words)))
          uncovered_indexes = all_indexes_set - covered_indexes_set
          uncovered_indexes = sorted(list(uncovered_indexes))
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
          with open(f'./rendered/data/{language}/script-processed-wav.json', 'w', encoding='utf-8') as f:
            f.write(json.dumps(script))
        resp.status = falcon.HTTP_202
        resp.media = {
           "script": script,
           "timeRanges": time_ranges
        }
        await asyncio.create_task(partial(self.process_audio, language, phrase, occ))
    async def process_audio(self, language, phrase, occ):
        mypath = f'./rendered/audio/{language}'
        for dir in phrase['path']:
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
        audio, sr = librosa.load(f"./sources/audio/{language}/{occ['file']}.wav")
        segment = audio[occ["start"]:occ["end"]]
        occ["full_path"] = f"{mypath}/{occ['path']}"
        wavpath = f"{mypath}/{occ['path'].replace('.wav', '.ogg')}"
        yt, index = librosa.effects.trim(segment)
        sf.write(wavpath, yt, sr, format='ogg', subtype='vorbis')

class SaveWaveformResource:
    def on_post(self, req, resp):
        data = req.media

        if 'wavData' not in data:
            raise falcon.HTTPBadRequest('Bad Request', 'WAV data not found in request')

        # Decode base64 WAV data
        base64_wav_data = data['wavData']
        wav_data = base64.b64decode(base64_wav_data)
        path = data["fullPath"]
        language = data["language"]
        script = data["script"]
        # Save the WAV data to a file
        with open(path, 'wb') as f:
            f.write(wav_data)
        y, sr = librosa.load(path)
        sf.write(path.replace('.wav', '.ogg'), y, sr, format='ogg', subtype='vorbis')
        with open(f'./rendered/data/{language}/script-processed-wav.json', 'w', encoding='utf-8') as f:
           f.write(json.dumps(script))
        resp.status = falcon.HTTP_200
        resp.media = {'message': 'OK'}
class SaveScriptResource:
    def on_post(self, req, resp):
        data = req.media
        script = data["script"]
        language = data["language"]
        with open(f'./rendered/data/{language}/script-processed-wav.json', 'w', encoding='utf-8') as f:
           f.write(json.dumps(script))
        resp.status = falcon.HTTP_200
        resp.media = {'message': 'OK'}
class SaveGameResource:
    def on_post(self, req, resp):
        data = req.media
        script = data["game"]
        language = data["language"]
        with open(f'./rendered/data/{language}/game.json', 'w', encoding='utf-8') as f:
           f.write(json.dumps(script))
        resp.status = falcon.HTTP_200
        resp.media = {'message': 'OK'}
class SaveSourcesResource:
    def on_post(self, req, resp):
        data = req.media
        sources = data["sources"]
        with open(f'./sources/sources.json', 'w', encoding='utf-8') as f:
           f.write(json.dumps(sources))
        resp.status = falcon.HTTP_200
        resp.media = {'message': 'OK'}
class UploadResource:
    def on_post(self, req, resp):
        data = req.media
        base64data = data["data"]
        name = data["name"]
        language = data.get("language") or 'en'
        file_extension = name.split('.')[-1].lower()
        file_name = sanitize_filename(get_filename_without_extension(name))
        id = data.get("id") or uuid.uuid4().hex[:8]
        fileData = base64.b64decode(base64data)
        temp_path = f'upload-temp/{file_name}.{file_extension}'
        with open(temp_path, 'wb') as f:
            f.write(fileData)

        # Determine the file type based on the file name or other attributes
        if file_extension in ('jpg', 'jpeg', 'png', 'dng', 'tiff', 'tif'):
            type = 'image'
            mypath = process_image(temp_path, file_name, id)
        elif file_extension in ('mp4', 'avi', 'mov', 'mkv'):
            type = 'video'
            mypath = process_video(temp_path, id)
        elif file_extension in ('wav', 'mp3', 'ogg'):
            type = 'audio'
            mypath = process_audio(temp_path, file_name, id, language)
        source_obj = {
            "id": id,
            "path": mypath,
            "filename": file_name,
            "extension": file_extension,
            "type": type
        }
        with open('sources/sources.json', 'r+', encoding='utf-8') as f:
            sources = json.load(f)
            sources.append(source_obj)
            f.seek(0)  # Move the file pointer to the beginning
            json.dump(sources, f, indent=4)  # Write the updated JSON data back to the file
            f.truncate()  # Truncate any remaining data after the updated content
        resp.status = falcon.HTTP_200
        resp.media = source_obj
class SegmentResource:
    def on_post(self, req, resp):
        data = req.media
        imgPath = data["imgPath"]
        maskBox = data["maskBox"]
        expand = data["expand"]
        blur = data["blur"]
        fillHoles = data["fillHoles"]
        image = cv2.imread(imgPath)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        predictor.set_image(image)
        input_box = np.array(maskBox)
        masks, scores, _ = predictor.predict(
            point_coords=None,
            point_labels=None,
            box=input_box[None, :],
            multimask_output=True,
        )
        combined_mask = np.zeros_like(masks[0], dtype=np.uint8)
        for i, mask in enumerate(masks):
            if fillHoles:
                filled_submask = fill_mask_outlines(mask, 1.0)
                expanded_submask = expand_and_blur_mask(filled_submask, expansion_pixels=expand, blur_kernel_size=blur)
            else:
                expanded_submask = expand_and_blur_mask(mask, expansion_pixels=expand, blur_kernel_size=blur)
            save_mask_as_bw(expanded_submask, imgPath, f'-mask{i}.png')
            combined_mask = np.logical_or(combined_mask, mask)
        if fillHoles:
            filled_mask = fill_mask_outlines(combined_mask, 1.0)
            expanded_blurred_mask = expand_and_blur_mask(filled_mask, expansion_pixels=expand, blur_kernel_size=blur)
        else:
            expanded_blurred_mask = expand_and_blur_mask(combined_mask, expansion_pixels=expand, blur_kernel_size=blur)
        # Save the expanded and blurred mask as an image
        save_mask_as_bw(expanded_blurred_mask, imgPath, '-mask.png')
        resp.status = falcon.HTTP_200
        resp.media = {
            'message': 'OK',
            'numMasks': len(masks)
        }

app = falcon.API()
print("Falcon version:", falcon.__version__)
error_handler = ErrorHandler()
awr = AssignWordsResource()
gasr = GetAudioSourcesResource()
swr = SaveWaveformResource()
ssr = SaveScriptResource()
sgr = SaveGameResource()
ssor = SaveSourcesResource()
ur = UploadResource()
sr = SegmentResource()
app.add_error_handler(Exception, error_handler)
app.add_route('/assign-words-to-line', awr)
app.add_route('/get-audio-sources', gasr)
app.add_route('/save-waveform', swr)
app.add_route('/save-script', ssr)
app.add_route('/save-game', sgr)
app.add_route('/save-sources', ssor)
app.add_route('/upload', ur)
app.add_route('/segment', sr)
app.add_static_route('/', f'{os.getcwd()}/')
app.add_static_route('/data', f'{os.getcwd()}/data')