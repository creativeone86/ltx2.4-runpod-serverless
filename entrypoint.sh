#!/bin/bash

set -e

echo "Checking network volume models..."
REQUIRED_MODELS=(
    "/runpod-volume/models/checkpoints/ltx-2.3-22b-dev.safetensors"
    "/runpod-volume/models/clip/comfy_gemma_3_12B_it.safetensors"
    "/runpod-volume/models/loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384.safetensors"
    "/runpod-volume/models/latent_upscale_models/ltx-2.3-spatial-upscaler-x2-1.0.safetensors"
)
MISSING=0
for model in "${REQUIRED_MODELS[@]}"; do
    if [ ! -f "$model" ]; then
        echo "ERROR: Model not found: $model"
        MISSING=1
    else
        echo "  Found: $(basename $model)"
    fi
done
if [ $MISSING -eq 1 ]; then
    echo ""
    echo "Network volume is not mounted or models are missing."
    echo "Please run setup_volume.sh on your network volume first."
    exit 1
fi
echo "All models found on network volume."

echo ""
echo "Starting ComfyUI in the background..."
python /ComfyUI/main.py --listen --use-sage-attention &

echo "Waiting for ComfyUI to be ready..."
max_wait=300
wait_count=0
while [ $wait_count -lt $max_wait ]; do
    if curl -s http://127.0.0.1:8188/ > /dev/null 2>&1; then
        echo "ComfyUI is ready!"
        break
    fi
    echo "Waiting for ComfyUI... ($wait_count/$max_wait)"
    sleep 2
    wait_count=$((wait_count + 2))
done

if [ $wait_count -ge $max_wait ]; then
    echo "Error: ComfyUI failed to start within $max_wait seconds"
    exit 1
fi

echo "Starting the handler..."
exec python handler.py
