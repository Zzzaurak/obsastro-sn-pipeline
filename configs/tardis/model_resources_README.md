# TARDIS Model Resources

This directory now separates two kinds of TARDIS inputs:

- `base_Ia.yml` and `SN2026*.yml`: runnable simulation configs.
- `model_resources.yml`: a manifest of density/abundance resources that can be copied or downloaded for future model tuning.

Prepare the resources with:

```bash
conda activate tardis
python scripts/download_tardis_model_resources.py
```

The script writes files under `data/tardis_models/` and creates `data/tardis_models/model_resources_index.csv`.
It does not run TARDIS and does not modify the current adopted target configs.

For future tuning, use these resources as candidate `csvy_model` files or as `model.structure.type=file` / `model.abundances.type=file` inputs. The format examples in `data/tardis_models/examples/` are meant as references before converting literature ejecta models into TARDIS-readable files.
