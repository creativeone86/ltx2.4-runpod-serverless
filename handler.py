import runpod
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.error
import urllib.parse
import binascii
import subprocess
import time
import random
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1')
client_id = str(uuid.uuid4())

DEFAULT_NEGATIVE_PROMPT = "pc game, console game, video game, cartoon, childish, ugly"

COMFYUI_INPUT_DIR = "/ComfyUI/input"


def to_nearest_multiple_of_32(value):
    try:
        numeric_value = float(value)
    except Exception:
        raise Exception(f"width/height value is not numeric: {value}")
    adjusted = int(round(numeric_value / 32.0) * 32)
    if adjusted < 32:
        adjusted = 32
    return adjusted


def process_input(input_data, temp_dir, output_filename, input_type):
    if input_type == "path":
        logger.info(f"Path input: {input_data}")
        return input_data
    elif input_type == "url":
        logger.info(f"URL input: {input_data}")
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        return download_file_from_url(input_data, file_path)
    elif input_type == "base64":
        logger.info("Base64 input")
        return save_base64_to_file(input_data, temp_dir, output_filename)
    else:
        raise Exception(f"Unsupported input type: {input_type}")


def download_file_from_url(url, output_path):
    try:
        result = subprocess.run(
            ['wget', '-O', output_path, '--no-verbose', url],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info(f"Downloaded: {url} -> {output_path}")
            return output_path
        else:
            raise Exception(f"Download failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise Exception("Download timed out")
    except Exception as e:
        raise Exception(f"Download error: {e}")


def save_base64_to_file(base64_data, temp_dir, output_filename):
    try:
        decoded_data = base64.b64decode(base64_data)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        with open(file_path, 'wb') as f:
            f.write(decoded_data)
        logger.info(f"Saved base64 to: {file_path}")
        return file_path
    except (binascii.Error, ValueError) as e:
        raise Exception(f"Base64 decode failed: {e}")


def copy_to_comfyui_input(source_path, target_filename):
    """Copy a file to ComfyUI's input directory so LoadImage/LoadAudio can find it."""
    os.makedirs(COMFYUI_INPUT_DIR, exist_ok=True)
    target_path = os.path.join(COMFYUI_INPUT_DIR, target_filename)
    shutil.copy2(source_path, target_path)
    logger.info(f"Copied to ComfyUI input: {target_path}")
    return target_filename


def get_audio_duration(audio_path):
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            duration = float(result.stdout.strip())
            logger.info(f"Audio duration: {duration:.2f}s")
            return duration
    except Exception as e:
        logger.warning(f"Failed to get audio duration: {e}")
    return None


def queue_prompt(prompt):
    url = f"http://{server_address}:8188/prompt"
    logger.info(f"Queueing prompt to: {url}")
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error(f"ComfyUI prompt rejected: HTTP {e.code} - {e.reason}")
        logger.error(f"ComfyUI response body: {body}")
        try:
            err_json = json.loads(body)
            logger.error(f"ComfyUI error (parsed): {json.dumps(err_json, indent=2)}")
        except Exception:
            pass
        raise


def get_history(prompt_id):
    url = f"http://{server_address}:8188/history/{prompt_id}"
    logger.info(f"Getting history from: {url}")
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def get_videos(ws, prompt):
    prompt_id = queue_prompt(prompt)['prompt_id']
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break

    history = get_history(prompt_id)[prompt_id]
    output_videos = {}

    # Log actual structure so we can fix extraction if SaveVideo uses different keys
    outputs = history.get('outputs', {})
    logger.info(f"History outputs node IDs: {list(outputs.keys())}")
    for nid, out in outputs.items():
        logger.info(f"  Node {nid} output keys: {list(out.keys()) if isinstance(out, dict) else type(out).__name__}")

    for node_id in outputs:
        node_output = outputs[node_id]
        videos_output = []
        # Support both list keys ('videos', 'gifs') and singular 'video'
        for key in ('videos', 'gifs', 'video'):
            if key not in node_output:
                continue
            items = node_output[key]
            if isinstance(items, dict):
                items = [items]
            elif not isinstance(items, list):
                continue
            for video in items:
                if not isinstance(video, dict):
                    continue
                fullpath = video.get('fullpath')
                if fullpath and os.path.exists(fullpath):
                    with open(fullpath, 'rb') as f:
                        video_data = base64.b64encode(f.read()).decode('utf-8')
                    videos_output.append(video_data)
                    logger.info(f"Read video from fullpath: {fullpath}")
                    continue
                filename = video.get('filename', '')
                subfolder = video.get('subfolder', '')
                output_dir = os.path.join('/ComfyUI/output', subfolder) if subfolder else '/ComfyUI/output'
                filepath = os.path.join(output_dir, filename)
                if os.path.exists(filepath):
                    with open(filepath, 'rb') as f:
                        video_data = base64.b64encode(f.read()).decode('utf-8')
                    videos_output.append(video_data)
                    logger.info(f"Read video from: {filepath}")
                    continue
                # Try filename only in /ComfyUI/output (no subfolder)
                if filename:
                    alt = os.path.join('/ComfyUI/output', filename)
                    if os.path.exists(alt):
                        with open(alt, 'rb') as f:
                            video_data = base64.b64encode(f.read()).decode('utf-8')
                        videos_output.append(video_data)
                        logger.info(f"Read video from alt path: {alt}")
                        continue
                logger.warning(f"Video entry not found on disk: fullpath={fullpath!r}, filepath={filepath!r}")
        if videos_output:
            output_videos[node_id] = videos_output

    return output_videos


def load_workflow(workflow_path):
    abs_path = os.path.abspath(workflow_path)
    logger.info(f"Loading workflow from: {abs_path} (exists: {os.path.exists(abs_path)})")
    with open(workflow_path, 'r') as file:
        data = json.load(file)
    # Log ResizeImageMaskNode inputs to debug longer_size / size mismatch
    for nid, node in data.items():
        if isinstance(node, dict) and node.get("class_type") == "ResizeImageMaskNode":
            logger.info(f"Workflow node {nid} (ResizeImageMaskNode) inputs: {json.dumps(node.get('inputs', {}), indent=2)}")
    return data


def handler(job):
    job_input = job.get("input", {})
    logger.info(f"Received job input keys: {list(job_input.keys())}")
    task_id = f"task_{uuid.uuid4()}"

    # --- Parse image input (first frame) ---
    image_path = None
    if "image_path" in job_input:
        image_path = process_input(job_input["image_path"], task_id, "input_image.jpg", "path")
    elif "image_url" in job_input:
        image_path = process_input(job_input["image_url"], task_id, "input_image.jpg", "url")
    elif "image_base64" in job_input:
        image_path = process_input(job_input["image_base64"], task_id, "input_image.jpg", "base64")

    # --- Parse last frame image input ---
    last_frame_path = None
    if "last_frame_image_path" in job_input:
        last_frame_path = process_input(job_input["last_frame_image_path"], task_id, "last_frame.jpg", "path")
    elif "last_frame_image_url" in job_input:
        last_frame_path = process_input(job_input["last_frame_image_url"], task_id, "last_frame.jpg", "url")
    elif "last_frame_image_base64" in job_input:
        last_frame_path = process_input(job_input["last_frame_image_base64"], task_id, "last_frame.jpg", "base64")

    # --- Parse audio input ---
    audio_path = None
    if "audio_path" in job_input:
        audio_path = process_input(job_input["audio_path"], task_id, "input_audio.mp3", "path")
    elif "audio_url" in job_input:
        audio_path = process_input(job_input["audio_url"], task_id, "input_audio.mp3", "url")
    elif "audio_base64" in job_input:
        audio_path = process_input(job_input["audio_base64"], task_id, "input_audio.mp3", "base64")

    is_img2vid = image_path is not None
    has_audio_input = audio_path is not None
    with_audio = job_input.get("with_audio", True)

    # --- Select workflow ---
    if has_audio_input:
        workflow_file = "/ltx23_audio_input_api.json"
        with_audio = True
    elif with_audio:
        workflow_file = "/ltx23_audio_api.json"
    else:
        workflow_file = "/ltx23_api.json"

    logger.info(f"Mode: {'i2v' if is_img2vid else 't2v'}, audio_input: {has_audio_input}, "
                f"with_audio: {with_audio}, workflow: {workflow_file}")

    prompt = load_workflow(workflow_file)

    # --- Parse parameters ---
    positive_prompt = job_input.get("prompt", "A cinematic video")
    negative_prompt = job_input.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)
    width = to_nearest_multiple_of_32(job_input.get("width", 960))
    height = to_nearest_multiple_of_32(job_input.get("height", 544))
    fps = float(job_input.get("fps", 24))

    if has_audio_input and "num_frames" not in job_input:
        audio_duration = get_audio_duration(audio_path)
        if audio_duration:
            num_frames = int(audio_duration * fps) + 1
            logger.info(f"Auto-calculated num_frames={num_frames} from audio ({audio_duration:.2f}s at {fps} fps)")
        else:
            num_frames = 121
    else:
        num_frames = job_input.get("num_frames", 121)
    seed = job_input.get("seed", random.randint(0, 2**32 - 1))
    distilled_lora_strength = float(job_input.get("distilled_lora_strength", 0.5))

    logger.info(f"Params: {width}x{height}, {num_frames} frames, {fps} fps, seed={seed}, lora={distilled_lora_strength}")

    # --- Inject text prompts ---
    prompt["2483"]["inputs"]["text"] = positive_prompt
    prompt["2612"]["inputs"]["text"] = negative_prompt

    # --- Inject video dimensions ---
    prompt["3059"]["inputs"]["width"] = width
    prompt["3059"]["inputs"]["height"] = height
    prompt["3059"]["inputs"]["length"] = num_frames

    # --- Inject frame rate ---
    prompt["1241"]["inputs"]["frame_rate"] = fps
    prompt["4849"]["inputs"]["fps"] = fps

    # --- Inject LoRA strength ---
    prompt["4922"]["inputs"]["strength_model"] = distilled_lora_strength

    # --- Inject seeds ---
    prompt["4832"]["inputs"]["noise_seed"] = seed
    prompt["4967"]["inputs"]["noise_seed"] = seed + 1

    # --- Handle first frame image (i2v mode) ---
    bypass_i2v = not is_img2vid
    prompt["3159"]["inputs"]["bypass"] = bypass_i2v
    prompt["4970"]["inputs"]["bypass"] = bypass_i2v

    if is_img2vid:
        image_filename = copy_to_comfyui_input(image_path, f"{task_id}_input.jpg")
        prompt["2004"]["inputs"]["image"] = image_filename
    else:
        prompt["2004"]["inputs"]["image"] = "example.png"

    # --- Handle audio input (a2v mode) ---
    if has_audio_input:
        audio_filename = copy_to_comfyui_input(audio_path, f"{task_id}_audio.mp3")
        prompt["5001"]["inputs"]["audio"] = audio_filename

    # --- Handle generated audio frame sync ---
    if with_audio and not has_audio_input and "3980" in prompt:
        prompt["3980"]["inputs"]["frames_number"] = num_frames
        prompt["3980"]["inputs"]["frame_rate"] = int(fps)

    # --- Debug: log workflow source and ResizeImageMaskNode state before queueing ---
    logger.info(f"About to queue prompt from workflow: {workflow_file}")
    for nid, node in prompt.items():
        if isinstance(node, dict) and node.get("class_type") == "ResizeImageMaskNode":
            inputs = node.get("inputs", {})
            logger.info(f"Prompt node {nid} (ResizeImageMaskNode) inputs before queue: {json.dumps(inputs, indent=2)}")
            if "longer_size" not in inputs:
                logger.warning(f"Prompt node {nid} missing 'longer_size' in inputs (ComfyUI will reject with 400)")

    # --- Connect to ComfyUI ---
    ws_url = f"ws://{server_address}:8188/ws?clientId={client_id}"
    http_url = f"http://{server_address}:8188/"
    logger.info(f"Waiting for ComfyUI at: {http_url}")

    max_http_attempts = 300
    for attempt in range(max_http_attempts):
        try:
            response = urllib.request.urlopen(http_url, timeout=5)
            logger.info(f"ComfyUI HTTP ready (attempt {attempt+1})")
            break
        except Exception as e:
            if attempt == max_http_attempts - 1:
                raise Exception("Cannot connect to ComfyUI server")
            time.sleep(1)

    ws = websocket.WebSocket()
    max_ws_attempts = 60
    for attempt in range(max_ws_attempts):
        try:
            ws.connect(ws_url)
            logger.info(f"WebSocket connected (attempt {attempt+1})")
            break
        except Exception as e:
            if attempt == max_ws_attempts - 1:
                raise Exception("WebSocket connection timeout")
            time.sleep(5)

    videos = get_videos(ws, prompt)
    ws.close()

    for node_id in videos:
        if videos[node_id]:
            return {"video": videos[node_id][0]}

    return {"error": "No video output found"}


runpod.serverless.start({"handler": handler})
