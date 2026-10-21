"""One approved experiment. Invoked only inside the Linux worker sandbox."""
from __future__ import annotations

import importlib.util
import json
import os
import resource
import sys
from pathlib import Path


def main():
    manifest = Path(sys.argv[1])
    output = Path(sys.argv[2])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    import observa
    from observa.validation import validate_strategy

    spec = json.loads(manifest.read_text())
    source = manifest.parent / spec["strategy_file"]
    sys.path[:0] = [str(source.parent), str(manifest.parent)]
    os.chdir(source.parent)
    validation = validate_strategy(str(source), class_name=spec.get("class_name"), smoke=True)
    (output / "validation.json").write_text(json.dumps(validation))
    if not validation["valid"]:
        raise ValueError("Strategy validation failed; see validation errors.")
    module_spec = importlib.util.spec_from_file_location("studio_strategy", source)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    strategy = getattr(module, validation["class"])
    config = observa.Config(**spec["config"])
    config.strategy_source = str(source)
    config.dataset_source = str(manifest.parent / "dataset.csv")
    observa.run(strategy, config.dataset_source, config=config, output=str(output / "run"))


if __name__ == "__main__":
    main()
