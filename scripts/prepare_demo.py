"""Build an explicitly labelled slideshow video from public held-out dataset images."""

import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not shutil.which("ffmpeg"):
        raise SystemExit("Install ffmpeg to prepare the optional sample video.")
    directory = ROOT / "data"
    images = directory / "datasets/ppe3/images/test"
    # These samples were chosen by content, not by the trained model's predictions.
    filenames = ["image1.jpeg", "image1003.jpg", "image1009.jpg", "image450.jpg"]
    intermediate = directory / "demo-intermediate.avi"
    writer = cv2.VideoWriter(str(intermediate), cv2.VideoWriter_fourcc(*"MJPG"), 10, (960, 540))
    if not writer.isOpened():
        raise SystemExit("Unable to create the sample video.")
    try:
        for filename in filenames:
            frame = cv2.imread(str(images / filename))
            if frame is None:
                raise ValueError(f"Missing sample: {filename}")
            height, width = frame.shape[:2]
            scale = min(960 / width, 540 / height)
            resized = cv2.resize(frame, (round(width * scale), round(height * scale)))
            canvas = np.full((540, 960, 3), (35, 28, 20), np.uint8)
            x, y = (960 - resized.shape[1]) // 2, (540 - resized.shape[0]) // 2
            canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
            for _ in range(60):
                writer.write(canvas)
    finally:
        writer.release()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(intermediate),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(directory / "demo.mp4"),
        ],
        check=True,
    )
    intermediate.unlink()
    (directory / "demo.json").write_text(
        json.dumps(
            {
                "description": (
                    "Учебный ролик из статических фотографий Construction-PPE. "
                    "Проверяет работу интерфейса и правил; не оценивает движение, "
                    "трекинг и качество на камерах предприятия."
                ),
                "source": "https://docs.ultralytics.com/datasets/detect/construction-ppe/",
                "license": "AGPL-3.0",
                "split": "test",
                "images": filenames,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(directory / "demo.mp4")


if __name__ == "__main__":
    main()
