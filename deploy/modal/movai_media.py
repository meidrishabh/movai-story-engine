"""MovAI's own image and video models on Modal.

Three GPU classes, each loaded once per container and kept warm for a couple of minutes between calls:

- QwenImage      text-to-image (Qwen/Qwen-Image, Apache 2.0). Used when a request has no reference images.
- QwenImageEdit  image generation from 1-3 reference images (Qwen/Qwen-Image-Edit-2509, Apache 2.0). Used for
                 character sheets drawn from the style anchor, and for keyframes drawn from character/place refs.
- WanVideo       image-to-video and text-to-video (Wan-AI/Wan2.2-TI2V-5B, Apache 2.0), 1280x704 at 24 fps, up to
                 121 frames (about 5 seconds) per clip.

The backend calls these through the Modal Python client (app/providers/media_modal.py), so there is no public HTTP
endpoint to protect: only someone holding your Modal token can call them.

Deploy once (and again after editing this file):
    modal deploy deploy/modal/movai_media.py

Try a prompt without the backend (makes a still with Qwen-Image, then animates it with Wan):
    modal run deploy/modal/movai_media.py --prompt "A lighthouse keeper climbs a spiral stair at dusk"
    modal run deploy/modal/movai_media.py --image keyframe.png --prompt "Camera pushes in slowly as she turns"

Weights are downloaded on first use into the `movai-hf-cache` volume, so only the first call of each class is slow.
GPU types can be changed at deploy time: MOVAI_IMAGE_GPU=A100-80GB MOVAI_VIDEO_GPU=A10 modal deploy ...
(The image models need about 60 GB; the 5B video model fits in 24 GB with CPU offload, 48 GB without.)
"""
import io
import os
import time

import modal

APP_NAME = "movai-media"
CACHE = "/cache"
IMAGE_GPU = os.environ.get("MOVAI_IMAGE_GPU", "H100")
VIDEO_GPU = os.environ.get("MOVAI_VIDEO_GPU", "L40S")
QWEN_IMAGE_MODEL = os.environ.get("MOVAI_QWEN_IMAGE_MODEL", "Qwen/Qwen-Image")
QWEN_EDIT_MODEL = os.environ.get("MOVAI_QWEN_EDIT_MODEL", "Qwen/Qwen-Image-Edit-2509")
WAN_MODEL = os.environ.get("MOVAI_WAN_MODEL", "Wan-AI/Wan2.2-TI2V-5B-Diffusers")
IDLE_SECONDS = int(os.environ.get("MOVAI_SCALEDOWN_SECONDS", "120"))  # warm time after a call; billed while warm

app = modal.App(APP_NAME)
cache = modal.Volume.from_name("movai-hf-cache", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .uv_pip_install(
        "torch==2.8.0",
        "diffusers==0.42.1",
        "transformers>=4.56,<5",
        "accelerate>=1.10",
        "sentencepiece",
        "ftfy",
        "imageio[ffmpeg]>=2.34",
        "pillow>=10",
        "huggingface_hub[hf_transfer]>=0.34",
    )
    .env({"HF_HOME": CACHE, "HF_HUB_ENABLE_HF_TRANSFER": "1", "TOKENIZERS_PARALLELISM": "false"})
)

# Sizes the models were trained around. The backend may ask for a small working size; generating at the native size
# and letting the render step scale down gives far better results than asking the model for 640x360.
QWEN_SIZES = {"16:9": (1664, 928), "9:16": (928, 1664), "1:1": (1328, 1328), "4:3": (1472, 1104),
              "3:4": (1104, 1472), "3:2": (1584, 1056), "2:3": (1056, 1584)}
WAN_SIZES = {"16:9": (1280, 704), "9:16": (704, 1280), "1:1": (960, 960)}
WAN_FPS = 24
WAN_MAX_FRAMES = 121


def _png(picture) -> bytes:
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def _open(data: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def _cover(picture, width: int, height: int):
    """Scale and centre-crop to exactly width x height (the first frame must match the video size)."""
    from PIL import Image

    scale = max(width / picture.width, height / picture.height)
    resized = picture.resize((max(width, round(picture.width * scale)), max(height, round(picture.height * scale))),
                             Image.LANCZOS)
    left, top = (resized.width - width) // 2, (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _generator(seed: int | None):
    import random

    import torch

    seed = int(seed) if seed is not None else random.randint(0, 2**31 - 1)
    return torch.Generator(device="cuda").manual_seed(seed), seed


@app.cls(gpu=IMAGE_GPU, image=image, volumes={CACHE: cache}, timeout=900, scaledown_window=IDLE_SECONDS,
         startup_timeout=1800)
class QwenImage:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import QwenImagePipeline

        self.pipe = QwenImagePipeline.from_pretrained(QWEN_IMAGE_MODEL, torch_dtype=torch.bfloat16).to("cuda")
        cache.commit()  # keep the downloaded weights for the next container

    @modal.method()
    def generate(self, prompt: str, negative_prompt: str = "", aspect_ratio: str = "16:9", seed: int | None = None,
                 steps: int = 50, true_cfg_scale: float = 4.0) -> dict:
        started = time.monotonic()
        width, height = QWEN_SIZES.get(aspect_ratio, QWEN_SIZES["16:9"])
        generator, seed = _generator(seed)
        result = self.pipe(prompt=prompt, negative_prompt=negative_prompt or " ", width=width, height=height,
                           num_inference_steps=steps, true_cfg_scale=true_cfg_scale, generator=generator,
                           max_sequence_length=1024).images[0]
        return {"png": _png(result), "width": result.width, "height": result.height, "seed": seed,
                "model": QWEN_IMAGE_MODEL, "gpu": IMAGE_GPU, "seconds": round(time.monotonic() - started, 2)}


@app.cls(gpu=IMAGE_GPU, image=image, volumes={CACHE: cache}, timeout=900, scaledown_window=IDLE_SECONDS,
         startup_timeout=1800)
class QwenImageEdit:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import QwenImageEditPlusPipeline

        self.pipe = QwenImageEditPlusPipeline.from_pretrained(QWEN_EDIT_MODEL, torch_dtype=torch.bfloat16).to("cuda")
        cache.commit()

    @modal.method()
    def generate(self, prompt: str, images: list[bytes], negative_prompt: str = "", aspect_ratio: str = "16:9",
                 seed: int | None = None, steps: int = 40, true_cfg_scale: float = 4.0) -> dict:
        if not images:
            raise ValueError("QwenImageEdit needs at least one reference image")
        started = time.monotonic()
        width, height = QWEN_SIZES.get(aspect_ratio, QWEN_SIZES["16:9"])
        generator, seed = _generator(seed)
        result = self.pipe(image=[_open(data) for data in images[:3]], prompt=prompt,
                           negative_prompt=negative_prompt or " ", width=width, height=height,
                           num_inference_steps=steps, true_cfg_scale=true_cfg_scale, generator=generator,
                           max_sequence_length=1024).images[0]
        return {"png": _png(result), "width": result.width, "height": result.height, "seed": seed,
                "model": QWEN_EDIT_MODEL, "gpu": IMAGE_GPU, "references_used": min(3, len(images)),
                "seconds": round(time.monotonic() - started, 2)}


@app.cls(gpu=VIDEO_GPU, image=image, volumes={CACHE: cache}, timeout=1800, scaledown_window=IDLE_SECONDS,
         startup_timeout=1800)
class WanVideo:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import AutoencoderKLWan, WanImageToVideoPipeline, WanPipeline

        # The Wan VAE is kept in float32, as the Wan model card recommends; everything else in bfloat16.
        vae = AutoencoderKLWan.from_pretrained(WAN_MODEL, subfolder="vae", torch_dtype=torch.float32)
        self.t2v = WanPipeline.from_pretrained(WAN_MODEL, vae=vae, torch_dtype=torch.bfloat16)
        # The 5B model does image-to-video with the same weights: the first frame is masked into the latents
        # (`expand_timesteps`), so no CLIP image encoder is needed. Share the loaded parts instead of loading twice.
        self.i2v = WanImageToVideoPipeline(tokenizer=self.t2v.tokenizer, text_encoder=self.t2v.text_encoder, vae=vae,
                                           scheduler=self.t2v.scheduler, transformer=self.t2v.transformer,
                                           expand_timesteps=True)
        if torch.cuda.get_device_properties(0).total_memory < 40 * 1024**3:
            self.t2v.enable_model_cpu_offload()  # 24 GB cards: slower, but fits
            self.i2v.enable_model_cpu_offload()
        else:
            self.t2v.to("cuda")
        cache.commit()

    @modal.method()
    def generate(self, prompt: str, negative_prompt: str = "", first_frame: bytes | None = None,
                 aspect_ratio: str = "16:9", duration_seconds: float = 5.0, seed: int | None = None, steps: int = 50,
                 guidance_scale: float = 5.0) -> dict:
        import math
        import tempfile

        from diffusers.utils import export_to_video

        started = time.monotonic()
        width, height = WAN_SIZES.get(aspect_ratio, WAN_SIZES["16:9"])
        wanted = max(1, math.ceil(float(duration_seconds) * WAN_FPS))
        frames = min(WAN_MAX_FRAMES, (wanted + 2) // 4 * 4 + 1)  # the model needs 4n+1 frames
        generator, seed = _generator(seed)
        common = {"prompt": prompt, "negative_prompt": negative_prompt or None, "width": width, "height": height,
                  "num_frames": frames, "num_inference_steps": steps, "guidance_scale": guidance_scale,
                  "generator": generator}
        if first_frame:
            output = self.i2v(image=_cover(_open(first_frame), width, height), **common).frames[0]
        else:
            output = self.t2v(**common).frames[0]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "clip.mp4")
            export_to_video(output, path, fps=WAN_FPS, quality=8)
            with open(path, "rb") as handle:
                data = handle.read()
        return {"mp4": data, "width": width, "height": height, "frames": frames, "fps": WAN_FPS,
                "duration_seconds": round(frames / WAN_FPS, 3), "seed": seed, "model": WAN_MODEL, "gpu": VIDEO_GPU,
                "mode": "image_to_video" if first_frame else "text_to_video",
                "seconds": round(time.monotonic() - started, 2)}


@app.local_entrypoint()
def main(prompt: str, image: str = "", motion: str = "", aspect_ratio: str = "16:9", seconds: float = 5.0,
         steps: int = 50, seed: int = -1, out: str = "movai_test"):
    """Quick check of a prompt. Without --image: still from --prompt, then animate it with --motion (or --prompt).
    With --image: animate that file with --prompt. Writes <out>.png and <out>.mp4 in the current folder."""
    seed_value = None if seed < 0 else seed
    if image:
        with open(image, "rb") as handle:
            still = handle.read()
        motion = motion or prompt
    else:
        made = QwenImage().generate.remote(prompt, aspect_ratio=aspect_ratio, seed=seed_value)
        still = made["png"]
        with open(f"{out}.png", "wb") as handle:
            handle.write(still)
        print(f"still: {out}.png  {made['width']}x{made['height']}  {made['seconds']}s on {made['gpu']}")
        motion = motion or prompt
    clip = WanVideo().generate.remote(motion, first_frame=still, aspect_ratio=aspect_ratio, duration_seconds=seconds,
                                      steps=steps, seed=seed_value)
    with open(f"{out}.mp4", "wb") as handle:
        handle.write(clip["mp4"])
    print(f"clip:  {out}.mp4  {clip['width']}x{clip['height']}  {clip['duration_seconds']}s  "
          f"{clip['seconds']}s on {clip['gpu']}  seed {clip['seed']}")
