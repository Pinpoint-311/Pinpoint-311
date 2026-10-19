# Demo GIS data

`backend/scripts/generate_demo_gis.py` builds **synthetic** GIS layers for a demo
or pilot instance, laid out on the instance's real road centrelines
(`road_segments`) inside its township boundary (system settings).
`backend/scripts/load_demo_gis.py` loads them through the app's own map-layer
code paths. None of it is an official record.

How it is marked:

- every layer name starts with `Demo — `, and every description contains
  "Synthetic demo data, not official records";
- every feature has `"demo": true`;
- owners are `DEMO OWNER 0001 (FICTIONAL)` and the like; street names are real,
  house numbers are made up.

## Layers

| Layer | Kind | Fields |
|---|---|---|
| Demo — Tax Parcels | polygon context layer, staff only | `PAMS_PIN` (MOD-IV `MUN_BLOCK_LOT`), `BLOCK`, `LOT`, `QUAL`, `PROP_LOC`, `PROP_CLASS` (1, 2, 4A, 4C, 15C, 15D), `LAND_VAL`, `IMPRVT_VAL`, `NET_VALUE`, `ACREAGE`, `ZONING`, `YEAR_BUILT`, `OWNER_NAME`, `PCL_MUN`, `MUN_NAME`, `COUNTY` |
| Demo — Trash Pickup Zones | polygon context layer, staff only | `ZONE_ID`, `ZONE_LABEL`, `TRASH_DAY`, `RECYCLING_WEEK`, `BULK_PICKUP` |
| Demo — Storm Drains | point | `asset_id` (SD-0001), `asset_type`, `STREET`, `INLET_TYPE`, `GRATE_MATERIAL`, `INSTALL_YEAR`, `LAST_CLEANED`, `CONDITION`, `OUTFALL_ID` |
| Demo — Fire Hydrants | point | `asset_id` (HYD-0001), `asset_type`, `STREET`, `FLOW_GPM`, `MAIN_SIZE_IN`, `COLOR_CODE` (NFPA 291), `LAST_FLUSHED`, `INSTALL_YEAR`, `STATUS` |
| Demo — Streetlights | point | `asset_id` (SL-0001), `asset_type`, `STREET`, `FIXTURE`, `WATTAGE`, `POLE_TYPE`, `OWNER` (Township/Utility), `INSTALL_YEAR` |
| Demo — Street Signs | point | `asset_id` (SIGN-0001), `asset_type`, `STREET`, `MUTCD_CODE`, `SIGN_TYPE`, `MESSAGE`, `INSTALL_YEAR`, `RETRO_RATING`, `POST_TYPE` |

The parcel layer's ID field is `PAMS_PIN` and its label is `PROP_LOC`. Its staff
allowlist leaves out `OWNER_NAME`, so the owner-field warnings show in the admin
console, and nothing owner-related ever reaches a report. Context layers stay
off the resident portal. Point layers are visible on the portal so residents can
pick an asset.

Category scoping is decided at load time. Each layer carries keywords (drains:
storm/drain/flood, hydrants: hydrant/water, lights: streetlight/lighting, signs:
sign/traffic, zones: trash/recycling/bulk/brush/leaf). A layer is scoped to the
active categories whose code or name contains one of its keywords. If none
matches, the layer applies to all categories. Parcels always apply to all.

## Configuration

Everything town-specific goes in a JSON config file that lives with the
instance, not in this repository. The format is in `configure()` in the
generator: the neighbourhood centres (lat/lng, radius, lot frontage/depth,
fictional zoning code, year-built range), the MOD-IV municipal code, name and
county, the point-layer target counts, and a seed. The output is deterministic:
the same config and road data give byte-identical files.

## Generate and load

Run both scripts inside the instance's backend container. They read the app's
DB settings from it.

```sh
STACK=<project>                       # e.g. the compose project name
C=$STACK-backend-1
docker exec $C mkdir -p /tmp/demo-gis-scripts
docker cp backend/scripts/generate_demo_gis.py $C:/tmp/demo-gis-scripts/
docker cp backend/scripts/load_demo_gis.py     $C:/tmp/demo-gis-scripts/
docker cp /path/to/demo-gis-config.json        $C:/tmp/demo-gis-config.json

# Take a backup first
docker exec $STACK-db-1 pg_dump -U <user> -d <db> -Fc > pre-demo-gis-$(date +%Y%m%d%H%M%S).dump

docker exec -w /app $C python /tmp/demo-gis-scripts/generate_demo_gis.py \
    --config /tmp/demo-gis-config.json --out /tmp/demo-gis
docker exec -w /app $C python /tmp/demo-gis-scripts/load_demo_gis.py load --in /tmp/demo-gis
```

`load` deletes every demo layer and then creates them again. Running it twice
leaves the same set of layers. After each context layer is created, the loader
backfills `gis_context` on existing reports (use `--no-backfill` to skip this).
It uses the app's admin handlers and writes audit rows as the first active admin
(use `--admin USERNAME` to pick another).

## Remove

```sh
docker exec -w /app $C python /tmp/demo-gis-scripts/load_demo_gis.py remove
docker exec -w /app $C python /tmp/demo-gis-scripts/load_demo_gis.py status   # lists what is left
```

`remove` deletes only layers that have both the `Demo — ` name prefix and the
"Synthetic demo data" marker in their description. Any other layer is left
alone. It also removes those layers' entries from reports' `gis_context`. The
timeline rows that the backfill wrote stay as history.
