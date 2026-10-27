"""Keep ML settings local to this project and disable optional online integrations."""

import os
from pathlib import Path


def configure_ml() -> None:
    config = Path(__file__).resolve().parents[1] / "data" / "ultralytics"
    config.mkdir(parents=True, exist_ok=True)
    os.environ["YOLO_CONFIG_DIR"] = str(config)
    from ultralytics import settings

    offline_integrations = (
        "sync",
        "hub",
        "comet",
        "mlflow",
        "wandb",
        "clearml",
        "neptune",
        "raytune",
    )
    settings.update({key: False for key in offline_integrations if key in settings})
