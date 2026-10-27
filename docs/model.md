# Model and data

The fine-tuned YOLO26n checkpoint has three classes: person, helmet, and vest. In the current live workflow, the original COCO YOLO26n detects people independently; the fine-tuned checkpoint supplies helmets and vests. Equipment is associated geometrically to current person boxes. This keeps person detection independent of equipment removal; it does not guarantee tracking continuity.

## Weights after cloning

Weights, training runs and datasets stay outside Git. The current local PPE checkpoint is identified by SHA-256 `c64f9e1c7ce09ea1594cbb797f19ca3be3febc776597677904cdf18d4ae711db`. The evaluation and training summary is in `reports/model-recovery-evaluation.json`.

To use the same model on another computer, transfer the trusted checkpoint separately, place it at `models/active/ppe-c64f9e1c7ce0.pt`, then run this from the repository root:

```bash
.venv/bin/python - <<'PY'
import hashlib
import json
from pathlib import Path

weights = Path('models/active/ppe-c64f9e1c7ce0.pt').resolve()
expected = 'c64f9e1c7ce09ea1594cbb797f19ca3be3febc776597677904cdf18d4ae711db'
assert hashlib.sha256(weights.read_bytes()).hexdigest() == expected, 'Unexpected weights'
manifest = {
    'path': str(weights),
    'weights_sha256': expected,
    'qualification': 'experimental-public-data-only',
    'metrics': {'mAP50 (test)': 0.8992213826110302, 'mAP50–95 (test)': 0.5248476310314606},
    'report': 'reports/model-recovery-evaluation.json',
}
Path('models/active.json').write_text(json.dumps(manifest, indent=2))
PY
```

The manifest contains an absolute path for the current computer, so copying an old `active.json` unchanged is insufficient. Transfer the original person checkpoint to `models/yolo26n.pt` as well. Alternatively, explicitly download the official pretrained person checkpoint using Ultralytics (requires network access):

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from ultralytics import YOLO

Path('models').mkdir(exist_ok=True)
YOLO(str(Path('models/yolo26n.pt').resolve()))
PY
```

Both files are needed for the current two-model workflow. Without the original person checkpoint the detector falls back to the person class of the PPE model. Without the PPE checkpoint the app can display its interface, but live recognition cannot start. If the PPE checkpoint is unavailable, reproduce training below; new training will produce a different hash and its own manifest.

## Reproduction

```bash
.venv/bin/python -m scripts.prepare_dataset
.venv/bin/python -m scripts.audit_images
.venv/bin/python -m scripts.clean_splits
.venv/bin/python -m scripts.train_ppe --epochs 15 --batch 8 --device mps
.venv/bin/python -m scripts.evaluate_model models/runs/<run>/weights/best.pt --activate
```

The preparation script downloads Construction-PPE and remaps source classes `6, 0, 2` to `0: person, 1: helmet, 2: vest`. Other labels are excluded from the target task, not reinterpreted as equipment absence.

The source archive and remapped data remain separate. Exact duplicate hashes are checked. A DCT perceptual-hash audit flags cross-split pairs at Hamming distance <= 8. The cleaning script conservatively removes train/validation examples linked to a higher-priority split, preserving final-test examples. Excluded examples remain on disk for inspection.

The current prepared split has 1,029 training images, 131 validation images, and 141 test images. Original camera/scene identifiers are unavailable: perceptual filtering cannot prove scene independence. The public dataset includes non-industrial examples and augmented images, so its metrics cannot be presented as factory-camera performance.

Training runs have unique directories and are not overwritten. A short initial probe measured hardware viability on the original public split; those weights are not the final evaluation candidate. Final training starts again from the official pretrained checkpoint after data cleaning.

`reports/model-evaluation.json` records held-out test metrics, class mapping, dataset preparation, and the weights SHA-256 when evaluation is complete. `models/active.json` selects an immutable local weight file. Only activate weights after inspecting their classes and evaluation.

## What still needs real evidence

- Recall for small people and small helmets on the actual camera view.
- Behavior in shadows, backlight, occlusions, night/IR scenes, and crowded zones.
- False alerts and missed events over full recordings, not only image AP.
- Correct association of equipment to people under overlap.
- CPU preparation time on the intended laptop and live-source performance if later added.

The optional demo is a labelled slideshow of held-out public photographs. It demonstrates UI/rule integration; it does not test motion or tracking.

## Sources

- [Ultralytics YOLO26](https://docs.ultralytics.com/models/yolo26/)
- [Training and Apple Silicon MPS](https://docs.ultralytics.com/modes/train/#apple-silicon-mps-training)
- [Construction-PPE dataset](https://docs.ultralytics.com/datasets/detect/construction-ppe/)

Ultralytics software and the dataset publish AGPL-3.0 terms; retain the upstream notices alongside downloaded artifacts.
