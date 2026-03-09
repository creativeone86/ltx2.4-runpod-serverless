#!/bin/bash
# Run this script ONCE on a temporary RunPod GPU pod with the network volume
# mounted at /workspace to download all LTX 2.3 models.
#
# On the pod:   models are at /workspace/models/
# On serverless: same files appear at /runpod-volume/models/

set -e

VOLUME_PATH="${1:-/workspace}"
MODELS_DIR="$VOLUME_PATH/models"

echo "========================================"
echo "LTX 2.3 Model Setup for Network Volume"
echo "Target: $MODELS_DIR"
echo "========================================"

echo ""
echo "Creating directory structure..."
mkdir -p "$MODELS_DIR/checkpoints"
mkdir -p "$MODELS_DIR/clip"
mkdir -p "$MODELS_DIR/loras/ltxv/ltx2"
mkdir -p "$MODELS_DIR/latent_upscale_models"

echo ""
echo "[1/4] Downloading ltx-2.3-22b-dev.safetensors (46.1 GB)..."
wget -O "$MODELS_DIR/checkpoints/ltx-2.3-22b-dev.safetensors" \
  "https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-dev.safetensors"

echo ""
echo "[2/4] Downloading Gemma 3 12B text encoder (24.4 GB)..."
wget -O "$MODELS_DIR/clip/comfy_gemma_3_12B_it.safetensors" \
  "https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it.safetensors"

echo ""
echo "[3/4] Downloading distilled LoRA (7.61 GB)..."
wget -O "$MODELS_DIR/loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384.safetensors" \
  "https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384.safetensors"

echo ""
echo "[4/4] Downloading spatial upscaler (996 MB)..."
wget -O "$MODELS_DIR/latent_upscale_models/ltx-2.3-spatial-upscaler-x2-1.0.safetensors" \
  "https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-spatial-upscaler-x2-1.0.safetensors"

echo ""
echo "========================================"
echo "Verifying downloads..."
echo "========================================"

FAIL=0
check_file() {
    if [ -f "$1" ]; then
        SIZE=$(du -h "$1" | cut -f1)
        echo "  OK: $1 ($SIZE)"
    else
        echo "  MISSING: $1"
        FAIL=1
    fi
}

check_file "$MODELS_DIR/checkpoints/ltx-2.3-22b-dev.safetensors"
check_file "$MODELS_DIR/clip/comfy_gemma_3_12B_it.safetensors"
check_file "$MODELS_DIR/loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384.safetensors"
check_file "$MODELS_DIR/latent_upscale_models/ltx-2.3-spatial-upscaler-x2-1.0.safetensors"

echo ""
if [ $FAIL -eq 0 ]; then
    echo "All models downloaded successfully!"
    echo "Total size: $(du -sh "$MODELS_DIR" | cut -f1)"
    echo ""
    echo "You can now terminate this pod."
    echo "Attach this volume to your serverless endpoint."
    echo "Models will be at /runpod-volume/models/ on serverless workers."
else
    echo "ERROR: Some models are missing. Check the output above."
    exit 1
fi
