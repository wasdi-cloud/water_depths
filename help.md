## Hydrothresholds Launcher

The Hydrothresholds Launcher prepares flood maps for processing by the `hydrothresholds` processor with enhanced water 
classification and visualization controls. It validates water presence, converts map formats, and optionally generates 
DEMs while providing permanent water handling features.

### Key Features

- Automatic Water Validation: Checks if flood maps contain actual water pixels before launching the `hydrothresholds` processor.
- Format Conversion: Converts three-state flood maps to simplified two-state format.
- Automatic DEM Generation: On-demand generation of a Digital Elevation Model via the dem_extractor if one is not provided.
- Permanent Water Control: Options to manage permanent water visualization.
- Internal Masking: For three-state flood maps, it can use the map's own permanent water class to create a perfect mask, 
eliminating all resampling artifacts.
- External Masking: For binary flood maps, it can automatically call the `world_cover_extractor` to generate a permanent 
water mask from global satellite data.

### Parameters

#### Main Parameters

- `FLOODMAP`: Input flood map filename.
- `THREE_STATE` (default to True): Parameter to identify whether the input flood map is in three-state or not.
- `DELETE_CONVERTED_FILE` (default is true): Set as "false" to keep the intermediate converted file.
- `OUTPUT_WATER_DEPTH`: Filename for the resulting water depth raster.
- `OUTPUT_WATER_SURFACE`: Filename for the resulting water surface elevation raster.
- `REMOVE_PERMANENT_WATER` (default is true): Exclude permanent water from the final output.
- `PERMANENT_WATER_AS_NO_DATA_VALUE` (default=-9999): Custom NoData value for permanent water in the final output 
(when `REMOVE_PERMANENT_WATER` is set as true).
- `PRODUCE_WSEM_OUTPUT` (default is false): Generate also the Water Surface Elevation Map as an output.
- `SIMULATE_HYDROTHRESHOLDS` (default is false): Test run without executing the `hydrothresholds` processor.

#### DEM Configuration

- `DEM`: Specify the DEM map filename if it is already present in the WS.
- `GENERATE_DEM` (default to true): Set it as True to generate DEM map with the `dem_extractor` if no file is available.
- `DEM_RES` (default to "DEM_30M"): Specify the DEM resolution for the DEM extractor in case new DEM map is to be generated.
- `DEM_DELETE` (default is true): Set it as False to keep the DEM map after processing.

#### Advanced Parameters for the `hydrothresholds` processor
- `ist` (Threshold Step) (default is 0.1): Increment step size used for threshold optimization search.
- `Patch Size` (default is 512): Size of each patch for individual analysis (in pixels).
- `Overlap` (default is 0.0): Pixel overlap ratio between adjacent patches to minimize edge effects (between 0 and 1).
- `SMOOTHING_WINDOW` (default is 256): Window size for smoothing threshold transitions between patches (in pixels). 
Set to 0 to disable. 

### Input Flood Map Conversion Logic:

#### Three-State Maps (when `THREE_STATE`=True)
```
0 → 255 (No data)
1 → 0   (Not flooded)
2 → 1   (Permanent water)*
3 → 1   (Flooded)
```
* Handled according to `REMOVE_PERMANENT_WATER` parameter

#### Two-State Maps (when `THREE_STATE`=False)
```
0 → 0 (Land)
1 → 1 (Water)
```

### Water Processing Modes

Control flood map processing with these parameters:
- `THREE_STATE`: Input map type (true=detailed 3-class, false=simple 2-class)
- `REMOVE_PERMANENT_WATER`: Whether to exclude permanent water from results

| Case | THREE_STATE | REMOVE_PW  | Behavior                                     | Best For                            |
|------|-------------|------------|----------------------------------------------|-------------------------------------|
| 1    | True        | True       | Isolates floodwater only using internal mask | Flood impact analysis               |
| 2    | True        | False      | Processes all water (permanent + flood)      | Hydraulic system analysis           |
| 3    | False       | True       | Uses WorldCover to estimate pw               | Simple maps needing water separation|
| 4    | False       | False      | Processes all water as single class          | Quick whole-area estimates          |

**Key Features:**
- Case 1/2: Uses original map's water classification
- Case 3: Generates external water mask using the `world_cover_extractor` (ESA WorldCover - class=80) automatically
- Case 4: Fastest processing for basic needs

All modes automatically remove artifacts arising from the `hydrothresholds` processing which are beyond the original 
water extents.

#### Visualization Tips

- In QGIS, use Layer Properties → Symbology to:
  - Set NoData value to your PERMANENT_WATER_AS_NO_DATA_VALUE 
  - Use "Singleband Pseudocolor" render type for flood visualization

- Enable/disable permanent water display using:
  - Right-click layer → Properties → Transparency 
  - Set "Additional no data value" to match your parameter

### JSON Sample
```JSON
{
    "FLOODMAP": "PW-Niamey_2024-08-25_flood.tif",
    "THREE_STATE": true,
    "REMOVE_PERMANENT_WATER": true,
    "PERMANENT_WATER_AS_NO_DATA_VALUE": -9999,
    "DELETE_CONVERTED_FILE": true,
    "DEM": "",
    "GENERATE_DEM": true,
    "DEM_RES": "DEM_30M",
    "DEM_DELETE": true,
    "OUTPUT_WATER_DEPTH": "PW-Niamey_WDM.tif",
    "OUTPUT_WATER_SURFACE": "PW-Niamey_WSEM.tif",
    "PRODUCE_WSEM_OUTPUT": true,
    "ist": 0.1,
    "PATCH_SIZE": 512,
    "OVERLAP": 0.25,
    "SMOOTHING_WINDOW": 256,
    "SIMULATE_HYDROTHRESHOLDS": false
}
```
