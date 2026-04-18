# Recipe vs legacy meshes — A/B swap notes

Three "structural anchor" kinds (stalagmite, column, mega_column) have BOTH
hand-authored GLBs (`{kind}_v{0-3}.glb`) and recipe-generated alternates
(`{kind}_recipe_v{0-3}.glb`), per the "C-lite" approach from the make_rock
erosion port discussion.

**Default runtime:** legacy GLBs are loaded. column / mega_column resolve
via `MESH_ALIAS` in `main.gd` (both alias to stalagmite). Recipe meshes
are produced and live alongside but the engine doesn't reach for them.

## Why both sides exist

Hand-authored versions were validated through hours of play (tag_03
"BEAUTIFUL" hit was specifically *"two angular columns frame the view"* —
the silhouettes are doing real composition work). Replacing them with
recipe-generated `tapered_vertical` output is non-zero visual risk.

But the recipe path is the canonical config-as-code direction
(per `design_config_as_code` + `design_north_star` Phase 3 modding).
Eventually all kinds should be recipe-built. C-lite ships the recipes
parked-but-ready so we can flip per-kind without losing the legacy
fallback if the recipe regresses something.

## How to flip ONE kind to recipe

Edit `godot/main.gd` `MESH_ALIAS` block (~line 362):

```gdscript
const MESH_ALIAS := {
    "buttress": "boulder",
    "mega_column": "stalagmite",   # ← change to "mega_column_recipe"
    "column": "stalagmite",        # ← change to "column_recipe"
}
```

For stalagmite (no alias), edit `_get_mesh_for_kind` directly OR add an
override that maps `"stalagmite": "stalagmite_recipe"` and remove the
two aliases above. Reload the Godot scene to see the swap.

## How to flip back

Revert the `MESH_ALIAS` edit. Or `git checkout godot/main.gd`.

## Regenerating recipe meshes

```bash
python tools/gen_kind_mesh.py stalagmite column mega_column
```

The `recipe.output_name` field in `config/kind_config.json` tells the
generator to emit to `_recipe` suffixed paths. Legacy GLBs are never
overwritten by this command.

## Future consolidation

When recipe versions are validated for all three kinds, drop the legacy
GLBs (`git rm godot/meshes/{stalagmite,column,mega_column}_v*.glb`),
remove the `output_name` field from kind_config so recipes generate at
the canonical filename, and clean up `MESH_ALIAS` aliases. Recipe
coverage would close to 8/8 and the alias workaround retires.
