#!/usr/bin/env python3
"""
LTX 2.3 Video Generation API Client
Client for generating videos using RunPod serverless endpoint with LTX 2.3 22B model.
Supports text-to-video, image-to-video, audio-to-video, and optional audio generation.
"""

import os
import requests
import json
import time
import base64
from typing import Optional, Dict, Any, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GenerateVideoClient:
    def __init__(self, runpod_endpoint_id: str, runpod_api_key: str):
        self.runpod_endpoint_id = runpod_endpoint_id
        self.runpod_api_key = runpod_api_key
        self.runpod_api_endpoint = f"https://api.runpod.ai/v2/{runpod_endpoint_id}/run"
        self.status_url = f"https://api.runpod.ai/v2/{runpod_endpoint_id}/status"

        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {runpod_api_key}',
            'Content-Type': 'application/json'
        })

        logger.info(f"GenerateVideoClient initialized - Endpoint: {runpod_endpoint_id}")

    def encode_file_to_base64(self, file_path: str) -> Optional[str]:
        try:
            if not os.path.exists(file_path):
                logger.error(f"File does not exist: {file_path}")
                return None
            with open(file_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"File base64 encoding failed: {e}")
            return None

    def submit_job(self, input_data: Dict[str, Any]) -> Optional[str]:
        payload = {"input": input_data}
        try:
            log_data = {k: v for k, v in input_data.items()
                        if k not in ("image_base64", "audio_base64")}
            if "image_base64" in input_data:
                log_data["image_base64"] = f"<{len(input_data['image_base64'])} chars>"
            if "audio_base64" in input_data:
                log_data["audio_base64"] = f"<{len(input_data['audio_base64'])} chars>"
            logger.info(f"Submitting job: {json.dumps(log_data, indent=2)}")

            response = self.session.post(self.runpod_api_endpoint, json=payload, timeout=30)
            response.raise_for_status()
            response_data = response.json()
            job_id = response_data.get('id')

            if job_id:
                logger.info(f"Job submitted: {job_id}")
                return job_id
            else:
                logger.error(f"No Job ID received: {response_data}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Job submission failed: {e}")
            return None

    def wait_for_completion(self, job_id: str, check_interval: int = 10, max_wait_time: int = 1800) -> Dict[str, Any]:
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            try:
                response = self.session.get(f"{self.status_url}/{job_id}", timeout=30)
                response.raise_for_status()
                status_data = response.json()
                status = status_data.get('status')

                elapsed = int(time.time() - start_time)
                logger.info(f"Job {job_id}: {status} ({elapsed}s elapsed)")

                if status == 'COMPLETED':
                    return {
                        'status': 'COMPLETED',
                        'output': status_data.get('output'),
                        'job_id': job_id
                    }
                elif status == 'FAILED':
                    return {
                        'status': 'FAILED',
                        'error': status_data.get('error', 'Unknown error'),
                        'job_id': job_id
                    }
                elif status in ('IN_QUEUE', 'IN_PROGRESS'):
                    time.sleep(check_interval)
                else:
                    return {
                        'status': 'UNKNOWN',
                        'data': status_data,
                        'job_id': job_id
                    }
            except requests.exceptions.RequestException as e:
                logger.error(f"Status check error: {e}")
                time.sleep(check_interval)

        return {'status': 'TIMEOUT', 'job_id': job_id}

    def save_video_result(self, result: Dict[str, Any], output_path: str) -> bool:
        try:
            if result.get('status') != 'COMPLETED':
                logger.error(f"Job not completed: {result.get('status')}")
                return False

            output = result.get('output', {})
            video_b64 = output.get('video')
            if not video_b64:
                logger.error("No video data in output")
                return False

            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            decoded_video = base64.b64decode(video_b64)
            with open(output_path, 'wb') as f:
                f.write(decoded_video)

            file_size = os.path.getsize(output_path)
            logger.info(f"Video saved: {output_path} ({file_size / (1024*1024):.1f} MB)")
            return True
        except Exception as e:
            logger.error(f"Video save failed: {e}")
            return False

    def generate_video(
        self,
        prompt: str,
        image_path: Optional[str] = None,
        image_url: Optional[str] = None,
        audio_path: Optional[str] = None,
        audio_url: Optional[str] = None,
        last_frame_image_path: Optional[str] = None,
        last_frame_image_url: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        width: int = 960,
        height: int = 544,
        num_frames: int = 121,
        fps: float = 24,
        seed: Optional[int] = None,
        with_audio: bool = True,
        distilled_lora_strength: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Generate video from text prompt, optionally conditioned on image and/or audio.

        Args:
            prompt: Text description of the desired video.
            image_path: Local image file path for image-to-video mode (first frame).
            image_url: Image URL for image-to-video mode (first frame).
            audio_path: Local audio file path for audio-to-video mode.
            audio_url: Audio URL for audio-to-video mode.
            last_frame_image_path: Local image file for last frame conditioning.
            last_frame_image_url: Image URL for last frame conditioning.
            negative_prompt: Text describing what to avoid.
            width: Output width (rounded to nearest multiple of 32, max 1600 for audio mode).
            height: Output height (rounded to nearest multiple of 32, max 900 for audio mode).
            num_frames: Number of frames to generate.
            fps: Frames per second.
            seed: Random seed for reproducibility.
            with_audio: Whether to generate synchronized audio (auto-enabled when audio_path/url provided).
            distilled_lora_strength: Strength of the distilled LoRA (0.0-1.0).

        Returns:
            Job result dictionary with status and output.
        """
        input_data: Dict[str, Any] = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "fps": fps,
            "with_audio": with_audio,
            "distilled_lora_strength": distilled_lora_strength,
        }

        if negative_prompt:
            input_data["negative_prompt"] = negative_prompt

        if seed is not None:
            input_data["seed"] = seed

        if image_path:
            if not os.path.exists(image_path):
                return {"error": f"Image file does not exist: {image_path}"}
            image_base64 = self.encode_file_to_base64(image_path)
            if not image_base64:
                return {"error": "Image base64 encoding failed"}
            input_data["image_base64"] = image_base64
        elif image_url:
            input_data["image_url"] = image_url

        if audio_path:
            if not os.path.exists(audio_path):
                return {"error": f"Audio file does not exist: {audio_path}"}
            audio_base64 = self.encode_file_to_base64(audio_path)
            if not audio_base64:
                return {"error": "Audio base64 encoding failed"}
            input_data["audio_base64"] = audio_base64
        elif audio_url:
            input_data["audio_url"] = audio_url

        if last_frame_image_path:
            if not os.path.exists(last_frame_image_path):
                return {"error": f"Last frame image does not exist: {last_frame_image_path}"}
            lf_base64 = self.encode_file_to_base64(last_frame_image_path)
            if not lf_base64:
                return {"error": "Last frame image base64 encoding failed"}
            input_data["last_frame_image_base64"] = lf_base64
        elif last_frame_image_url:
            input_data["last_frame_image_url"] = last_frame_image_url

        job_id = self.submit_job(input_data)
        if not job_id:
            return {"error": "Job submission failed"}

        return self.wait_for_completion(job_id)

    def batch_generate(
        self,
        prompts_and_images: List[Dict[str, Any]],
        output_folder: str,
        common_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Batch process multiple video generation jobs.

        Args:
            prompts_and_images: List of dicts, each with at least 'prompt' and
                optionally 'image_path', 'image_url', 'audio_path', 'audio_url',
                or other per-job overrides.
            output_folder: Directory to save output videos.
            common_params: Shared parameters applied to all jobs (width, height, etc.).

        Returns:
            Batch result summary.
        """
        os.makedirs(output_folder, exist_ok=True)
        if common_params is None:
            common_params = {}

        results = {
            "total": len(prompts_and_images),
            "successful": 0,
            "failed": 0,
            "details": []
        }

        for i, job_spec in enumerate(prompts_and_images):
            merged = {**common_params, **job_spec}
            prompt = merged.pop("prompt", "A cinematic video")
            image_path = merged.pop("image_path", None)
            image_url = merged.pop("image_url", None)
            audio_path = merged.pop("audio_path", None)
            audio_url = merged.pop("audio_url", None)

            logger.info(f"[{i+1}/{len(prompts_and_images)}] Generating: {prompt[:80]}...")

            result = self.generate_video(
                prompt=prompt,
                image_path=image_path,
                image_url=image_url,
                audio_path=audio_path,
                audio_url=audio_url,
                **merged
            )

            output_path = os.path.join(output_folder, f"video_{i:04d}.mp4")
            if result.get('status') == 'COMPLETED':
                if self.save_video_result(result, output_path):
                    results["successful"] += 1
                    results["details"].append({"index": i, "status": "success", "file": output_path})
                else:
                    results["failed"] += 1
                    results["details"].append({"index": i, "status": "save_failed"})
            else:
                results["failed"] += 1
                results["details"].append({
                    "index": i,
                    "status": "failed",
                    "error": result.get('error', 'Unknown')
                })

        logger.info(f"Batch complete: {results['successful']}/{results['total']} successful")
        return results


def main():
    """Usage examples for LTX 2.3 Video Generation Client."""

    ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID", "your-endpoint-id")
    API_KEY = os.getenv("RUNPOD_API_KEY", "your-api-key")

    client = GenerateVideoClient(
        runpod_endpoint_id=ENDPOINT_ID,
        runpod_api_key=API_KEY
    )

    # --- Example 1: Text-to-Video with generated audio ---
    print("=== Text-to-Video (with generated audio) ===")
    result = client.generate_video(
        prompt="A serene mountain landscape at sunrise with birds flying across the sky",
        width=960,
        height=544,
        num_frames=121,
        fps=24,
        seed=42,
        with_audio=True,
    )
    if result.get('status') == 'COMPLETED':
        client.save_video_result(result, "./output_t2v_audio.mp4")

    # --- Example 2: Text-to-Video without audio ---
    print("\n=== Text-to-Video (no audio) ===")
    result = client.generate_video(
        prompt="A futuristic city at night with neon lights reflecting off wet streets",
        width=960,
        height=544,
        num_frames=121,
        seed=123,
        with_audio=False,
    )
    if result.get('status') == 'COMPLETED':
        client.save_video_result(result, "./output_t2v_silent.mp4")

    # --- Example 3: Image-to-Video with generated audio ---
    print("\n=== Image-to-Video (with generated audio) ===")
    result = client.generate_video(
        prompt="The scene comes alive with gentle movement and ambient sounds",
        image_path="./example_image.png",
        width=960,
        height=544,
        num_frames=121,
        seed=42,
        with_audio=True,
    )
    if result.get('status') == 'COMPLETED':
        client.save_video_result(result, "./output_i2v_audio.mp4")

    # --- Example 4: Audio-to-Video (infinite talk mode) ---
    print("\n=== Audio-to-Video (audio input + image) ===")
    result = client.generate_video(
        prompt="A person speaking passionately to the camera",
        image_path="./speaker_photo.jpg",
        audio_path="./speech.mp3",
        width=720,
        height=720,
        num_frames=121,
        seed=42,
    )
    if result.get('status') == 'COMPLETED':
        client.save_video_result(result, "./output_a2v.mp4")

    # --- Example 5: Audio-to-Video with URL inputs ---
    print("\n=== Audio-to-Video (URL inputs) ===")
    result = client.generate_video(
        prompt="A musician performing on stage",
        image_url="https://example.com/musician.jpg",
        audio_url="https://example.com/performance.mp3",
        width=960,
        height=544,
        num_frames=121,
    )
    if result.get('status') == 'COMPLETED':
        client.save_video_result(result, "./output_a2v_url.mp4")

    print("\n=== All examples completed ===")


if __name__ == "__main__":
    main()
