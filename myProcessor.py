import os
import numpy as np
import rasterio
import wasdi
import os.path
from rasterio.warp import reproject, Resampling


def getFloodMapInfo(sFloodMapPath):
    """
        Extracts essential geospatial metadata and data from a flood map raster.
        Args:
            sFloodMapPath (str): Path to the input flood map GeoTIFF file
        Returns:
            dict: Dictionary containing:
                - data (np.ndarray): 2D numpy array of raster values
                - profile (dict): Rasterio profile dictionary with metadata
                - transform (Affine): Geotransform for the raster
                - crs (CRS): Coordinate reference system
                - bbox (dict): Bounding box coordinates in format:
                    {
                        "northEast": {"lat": ymax, "lng": xmax},
                        "southWest": {"lat": ymin, "lng": xmin}
                    }
        """
    with rasterio.open(sFloodMapPath) as src:
        oBbox = {
            "northEast": {"lat": src.bounds.top, "lng": src.bounds.right},
            "southWest": {"lat": src.bounds.bottom, "lng": src.bounds.left}
        }
        return {
            "data": src.read(1),
            "profile": src.profile,
            "transform": src.transform,
            "crs": src.crs,
            "bbox": oBbox
        }


def processFloodMap(sInputFile, oFloodMapInfo, bThreeState):
    """
    Processes flood map data according to classification type (2-state or 3-state).
    Args:
        sInputFile (str): Name of input flood map file
        oFloodMapInfo (dict): Flood map metadata from getFloodMapInfo()
        bThreeState (bool): Flag indicating if map uses 3-state classification
            - True: Values 0 (land), 2 (permanent water), 3 (flooded)
            - False: Values 0 (land), 1 (water)
    Returns:
        tuple: (processed_filename, permanent_water_mask_array) where:
            - processed_filename (str): Path to converted file or "NO_WATER"
            - permanent_water_mask_array (np.ndarray): Binary mask for permanent water
              (None for two-state maps or if no water detected)
    Raises:
        Logs errors through wasdi.wasdiLog() but doesn't raise exceptions
    Processing Logic:
        - Three-state maps:
            1. Creates permanent water mask (where value == 2)
            2. Merges water classes (values 2 & 3 → 1)
            3. Returns converted file and water mask
        - Two-state maps:
            1. Simply verifies water presence
            2. Returns original file (no conversion needed)
    """
    try:
        wasdi.wasdiLog("Processing input flood map data in memory")
        aiData = oFloodMapInfo["data"]
        pProfile = oFloodMapInfo["profile"]
        wasdi.wasdiLog(f"Input flood map values found: {np.unique(aiData)}")
        aiPermanentWaterMask = None

        # Function to save the resampled data as a GeoTIFF file
        def saveModifiedData(aiModifiedData, sOutputFile, pProfile, pCRS, pTransform, iNoDataValue):
            pProfile.update(dtype=aiModifiedData.dtype, nodata=iNoDataValue)
            with rasterio.open(wasdi.getPath(sOutputFile), 'w', **pProfile) as dst:
                dst.write(aiModifiedData, 1)

        if bThreeState: ### Cases 1 and 2 (THREE_STATE is True)
            # For any three-state map, we now create the mask and merge the water
            wasdi.wasdiLog("Three-state map: Creating in-memory permanent water mask (where value is 2).")
            # Create a binary mask where permanent water (value 2) is 1, others are 0
            aiPermanentWaterMask = (aiData == 2).astype(np.uint8)
            bHasWater = np.any((aiData == 2) | (aiData == 3))
            if not bHasWater: return ("NO_WATER", None)

            wasdi.wasdiLog("Three-state map: Merging permanent and flooded water for hydraulic consistency.")
            sModFile = sInputFile.replace('.tif', '_converted.tif')
            iNoDataValue = 255
            aiModifiedData = np.select(
                [
                    (aiData == 0),  # Condition 1: No data
                    np.logical_or(aiData == 2, aiData == 3)  # Condition 2: Permanent water or Flooded
                ],
                [iNoDataValue, 1],  # 255: No data, 1: Flooded+Permanent water
                default=0  # All others set to 0: Not Flooded
            )
            aiModifiedData = aiModifiedData.astype(pProfile['dtype'])
            saveModifiedData(aiModifiedData, sModFile, pProfile, oFloodMapInfo["crs"], oFloodMapInfo["transform"], iNoDataValue)
            wasdi.wasdiLog(f"Converted flood map saved to {sModFile}")
            wasdi.addFileToWASDI(sModFile, "wd_0_0.5m_YGB")
            return (sModFile, aiPermanentWaterMask)
        else: ### Cases 3 and 4 (THREE_STATE is False)
            # Two-state map: check for water and return
            bHasWater = np.any(aiData == 1)
            if not bHasWater: return ("NO_WATER", None)
            return (sInputFile, None) # Return None for the mask

    except Exception as oEx:
        wasdi.wasdiLog(f"Error in processing the input flood map: {str(oEx)}")
        return (None, None)


def processOutputArray(aiRawData, pProfile, abPermanentWaterMask=None, abFloodedMask=None, iPermanentWaterNoDataParam=-9999):
     """
    Processes raster data array with three-way classification:
    Args:
        aiRawData: Input numpy array
        pProfile: Rasterio profile dict
        abPermanentWaterMask: Boolean mask for permanent water
        abFloodedMask: Boolean mask for flooded areas
        iPermanentWaterNoDataParam: Value for permanent water (default -9999)
    Returns:
        np.ndarray with:
            - Permanent water = iPermanentWaterNoDataParam
            - Flooded areas = original values
            - Other areas = NaN
    """
     # Initialize with NaN (transparent)
     output = np.full_like(aiRawData, np.nan, dtype=np.float32)
     # Set flooded areas (keep original values)
     if abFloodedMask is not None:
        output[abFloodedMask] = aiRawData[abFloodedMask]
     else:
        # Default: treat non-NoData values as flooded
        output[aiRawData != pProfile.get('nodata', np.nan)] = aiRawData[aiRawData != pProfile.get('nodata', np.nan)]
        # Set permanent water to user-defined NoData value
     if abPermanentWaterMask is not None:
         output[abPermanentWaterMask] = iPermanentWaterNoDataParam
     return output

def saveOutputWithNoData(sOutputPath, afData, pProfile, iPermanentWaterNoDataParam=-9999):
    """
    Saves raster with proper NoData handling
    Args:
        sOutputPath: Output file path
        afData: Processed numpy array
        pProfile: Rasterio profile dict
        iPermanentWaterNoDataParam: NoData value (default -9999)
    """
    modified_profile = pProfile.copy()
    modified_profile.update(
        dtype='float32',
        nodata=iPermanentWaterNoDataParam,
        compress='lzw'
    )
    with rasterio.open(sOutputPath, 'w', **modified_profile) as dst:
        dst.write(afData.astype('float32'), 1)
        # Critical tags for QGIS visualization
        dst.update_tags(
            TIFFTAG_GDAL_NODATA=str(iPermanentWaterNoDataParam),  # Ensures GDAL recognizes iPermanentWaterAsNoData as NoData
            STATISTICS_MINIMUM="0",  # Force minimum to 0
            STATISTICS_MAXIMUM=str(np.nanmax(afData))  # Actual flooded max
        )

def run():
    try:
        wasdi.wasdiLog("Starting Hydrothresholds Launcher v.0.1.0")

        # --- 1. Parameter Retrieval --- #
        # Parameter to identify whether the images are in three state or not
        bThreeState = wasdi.getParameter('THREE_STATE', True)
        # Flag to delete the converted file
        bDeleteConvertedFile =  wasdi.getParameter('DELETE_CONVERTED_FILE', True)
        # Parameter to generate DEM
        bGenerateDEM = wasdi.getParameter('GENERATE_DEM', True)
        # Parameter to get the required DEM resolution
        sDEMResolution = wasdi.getParameter('DEM_RES', "DEM_30M")
        # Flag to delete the generated DEM file
        bDeleteDEMFile =  wasdi.getParameter('DEM_DELETE', True)
        # Flag to remove permanent water from output
        bRemovePermanentWater =  wasdi.getParameter('REMOVE_PERMANENT_WATER', True)
        # Value to be assigned for permanent water when it is taken as No-Data
        iPermanentWaterAsNoData = wasdi.getParameter('PERMANENT_WATER_AS_NO_DATA_VALUE', -9999)
        # Flag to conditionally produce the WSEM file
        bProduceWSEMFile = wasdi.getParameter('PRODUCE_WSEM_OUTPUT', False)
        # New simulation flag for testing
        bSimulateHydrothresholds = wasdi.getParameter('SIMULATE_HYDROTHRESHOLDS', False)

        # Initialize payload
        aoPayload = {}
        aoPayload['INPUT'] = wasdi.getParametersDict()
        wasdi.setPayload(aoPayload)

        # Retrieve and validate parameters
        aoHydroParams = wasdi.getParametersDict()
        sFloodMapName = aoHydroParams.get("FLOODMAP")
        if not sFloodMapName: raise ValueError("FLOODMAP parameter is required")

        # Verify input file exists
        sFloodMapPath = wasdi.getPath(sFloodMapName)
        if not os.path.exists(sFloodMapPath): raise FileNotFoundError(f"Flood map file not found: {sFloodMapPath}")

        # --- 2. Single File Read for Efficiency --- #
        wasdi.wasdiLog(f"Reading info from the input flood map: {sFloodMapName}")
        oFloodMapInfo = getFloodMapInfo(sFloodMapPath)
        oBbox = oFloodMapInfo["bbox"]
        # Get the base name from input flood map name
        sBaseName = sFloodMapName.split('_')[0] if "_" in sFloodMapName else sFloodMapName.replace('.tif', '')

        # ---- 3. External Mask Generation (if needed for Case 3) ---- #
        sPermanentWaterMaskFile = None
        if not bThreeState and bRemovePermanentWater:
            wasdi.wasdiLog("Case 3: Two-state map with permanent water removal. Generating external mask.")
            sMaskOutputName = f"{sBaseName}_PW_Mask.tif"
            aoWCExtractorParams = {"BBOX": oBbox, "OUTPUT": sMaskOutputName.replace('.tif', '_full.tif')}
            sProcId = wasdi.executeProcessor("world_cover_extractor", aoWCExtractorParams)
            sState = wasdi.waitProcess(sProcId)

            if sState != "DONE":
                raise RuntimeError(f"world_cover_extractor failed with status {sState}")

            sFullWCFile = aoWCExtractorParams["OUTPUT"]
            with rasterio.open(wasdi.getPath(sFullWCFile)) as src:
                pMaskProfile = src.profile
                aiFullWCData = src.read(1)
                aiBinaryMask = (aiFullWCData == 80).astype(np.uint8)
                pMaskProfile.update(dtype='uint8', compress='lzw', nodata=0)

            with rasterio.open(wasdi.getPath(sMaskOutputName), 'w', **pMaskProfile) as dst:
                dst.write(aiBinaryMask, 1)

            wasdi.addFileToWASDI(sMaskOutputName)
            sPermanentWaterMaskFile = sMaskOutputName
            wasdi.deleteProduct(sFullWCFile)

        # ---- 4. Flood Map Pre-Processing ---- #
        sProcessedFloodMapName, aiPermanentWaterMask = processFloodMap(sFloodMapName, oFloodMapInfo, bThreeState)

        if sProcessedFloodMapName == "NO_WATER":
            wasdi.wasdiLog("No water detected in the input map - hydrothresholds app not launched.")
            wasdi.updateStatus("DONE", 100)
            return
        elif not sProcessedFloodMapName:
            raise RuntimeError("Flood map pre-processing failed")
        aoHydroParams["FLOODMAP"] = sProcessedFloodMapName

        # ---- 5. DEM Generation (if needed) ---- #
        if bGenerateDEM and (aoHydroParams.get("DEM") == "" or aoHydroParams.get("DEM") == None):
            wasdi.wasdiLog('Starting dem_extractor')
            sTargetDemFilename = aoHydroParams.get("DEM_OUTPUT")
            if sTargetDemFilename is None or sTargetDemFilename == "":
                sTargetDemFilename = f"{sBaseName}_DEM.tif"

            aoInputsDEMExtractor = {}
            aoInputsDEMExtractor["BBOX"] = oBbox
            aoInputsDEMExtractor["DEM_RES"] = sDEMResolution
            aoInputsDEMExtractor["OUTPUT"] = sTargetDemFilename
            aoInputsDEMExtractor["DELETE"] = True

            sDEMExtractorProcessID = wasdi.executeProcessor("dem_extractor", aoInputsDEMExtractor)
            sDEMExtractorProcessStatus = wasdi.waitProcess(sDEMExtractorProcessID)

            if sDEMExtractorProcessStatus != "DONE":
                raise RuntimeError(f"The dem_extractor processor failed with status: '{sDEMExtractorProcessStatus}'.")

            aoDEMExtractorPayload = wasdi.getProcessorPayloadAsJson(sDEMExtractorProcessID)
            sGeneratedDemFilename = aoDEMExtractorPayload.get("output")
            if not sGeneratedDemFilename:
                raise RuntimeError("DEM could not be generated correctly by dem_extractor.")

            aoHydroParams["DEM"] = sGeneratedDemFilename
            aoRunResult = {"DEM_PROCID": sDEMExtractorProcessID}
            aoPayload["RUNS"] = aoRunResult
            wasdi.setPayload(aoPayload)

        else:
            wasdi.wasdiLog("New DEM file not generated")

        # ---- 6. Default output name generation ---- #
        sOutputWaterDepth = aoHydroParams.get("OUTPUT_WATER_DEPTH")
        if not sOutputWaterDepth or sOutputWaterDepth == "":
            sOutputWaterDepth = f"{sBaseName}_WDM.tif"
            aoHydroParams["OUTPUT_WATER_DEPTH"] = sOutputWaterDepth

        if bProduceWSEMFile:
            sOutputWaterSurface = aoHydroParams.get("OUTPUT_WATER_SURFACE")
            if not sOutputWaterSurface or sOutputWaterSurface == "":
                sOutputWaterSurface = f"{sBaseName}_WSEM.tif"
                aoHydroParams["OUTPUT_WATER_SURFACE"] = sOutputWaterSurface

        # ---- 7. Call or Simulate the hydrothresholds processor ---- #
        aoFinalOutputs = {}
        if not bSimulateHydrothresholds:
            wasdi.wasdiLog("Launching hydrothresholds processor")
            sHydroProcessId = wasdi.executeProcessor("hydrothresholds", aoHydroParams)
            sHydroProcessStatus = wasdi.waitProcess(sHydroProcessId)
            if sHydroProcessStatus != "DONE":
                raise RuntimeError(f"hydrothresholds processor failed with status: {sHydroProcessStatus}")

            aoPayload.setdefault("RUNS", {})["HYDROTHESHOLDS_PROCID"] = sHydroProcessId
            aoHydroProcessPayload = wasdi.getProcessorPayloadAsJson(sHydroProcessId)
            aoFinalOutputs = aoHydroProcessPayload["Output"]
        else:
            wasdi.wasdiLog("SIMULATION ENABLED: Skipping hydrothresholds processor execution.")
            aoFinalOutputs = {"WaterDepth": aoHydroParams.get("OUTPUT_WATER_DEPTH")}
            if bProduceWSEMFile:
                aoFinalOutputs["WaterSurfaceElevation"] = aoHydroParams.get("OUTPUT_WATER_SURFACE")

        aoPayload["FINAL_OUTPUT"] = aoFinalOutputs
        wasdi.setPayload(aoPayload)

        # ---- 8. Output Post-processing ---- #
        wasdi.wasdiLog("Starting final output post-processing.")
        sWaterDepthMap = aoFinalOutputs.get("WaterDepth")
        sWaterSurfaceMap = aoFinalOutputs.get("WaterSurfaceElevation")

        # Read Raw Data from hydrothresholds outputs
        if sWaterDepthMap:
            sWDMPath = wasdi.getPath(sWaterDepthMap)
            with rasterio.open(sWDMPath, 'r') as src:
                pWDMProfile = src.profile
                aiRawWDMData = src.read(1)
                fStandardNoData = pWDMProfile.get('nodata', np.nan)

        if bProduceWSEMFile and sWaterSurfaceMap:
            sWSEMPath = wasdi.getPath(sWaterSurfaceMap)
            with rasterio.open(sWSEMPath, 'r') as src:
                pWSEMProfile = src.profile
                aiRawWSEMData = src.read(1)

        # Apply processing based on the case
        if bThreeState and bRemovePermanentWater:  # Case 1
            wasdi.wasdiLog("Case 1: Three-state with permanent water removal")
            original_data = oFloodMapInfo["data"]
            abPermanentWaterMask = (original_data == 2)
            abFloodedMask = (original_data == 3)

            if aiRawWDMData is not None:
                aiFinalWDMData = processOutputArray(aiRawWDMData, pWDMProfile, abPermanentWaterMask, abFloodedMask,
                                                      iPermanentWaterNoDataParam=iPermanentWaterAsNoData)

            if bProduceWSEMFile and 'aiRawWSEMData' in locals():
                aiFinalWSEMData = processOutputArray(aiRawWSEMData, pWSEMProfile, abPermanentWaterMask, abFloodedMask,
                                                       iPermanentWaterNoDataParam=iPermanentWaterAsNoData)

        elif not bThreeState and bRemovePermanentWater:  # Case 3
            wasdi.wasdiLog("Case 3: Two-state with external permanent water mask")
            if sPermanentWaterMaskFile:
                with rasterio.open(wasdi.getPath(sPermanentWaterMaskFile)) as mask_src:
                    aiAlignedMask = np.empty(aiRawWDMData.shape, dtype=np.uint8)
                    reproject(
                        source=rasterio.band(mask_src, 1), destination=aiAlignedMask,
                        dst_transform=pWDMProfile['transform'], dst_crs=pWDMProfile['crs'],
                        dst_nodata=0, resampling=Resampling.nearest
                    )

                if aiRawWDMData is not None:
                    aiFinalWDMData = processOutputArray(aiRawWDMData, pWDMProfile, aiAlignedMask == 1,
                                                          iPermanentWaterNoDataParam=iPermanentWaterAsNoData)

                if bProduceWSEMFile and 'aiRawWSEMData' in locals():
                    aiFinalWSEMData = processOutputArray(aiRawWSEMData, pWSEMProfile, aiAlignedMask == 1,
                                                           iPermanentWaterNoDataParam=iPermanentWaterAsNoData)
            else:
                wasdi.wasdiLog("Warning: External mask not generated, skipping removal")
                aiFinalWDMData = processOutputArray(aiRawWDMData, pWDMProfile)
                if bProduceWSEMFile and 'aiRawWSEMData' in locals():
                    aiFinalWSEMData = processOutputArray(aiRawWSEMData, pWSEMProfile)

        else:  # Cases 2 & 4
            wasdi.wasdiLog(f"Case {'2' if bThreeState else '4'}: No permanent water removal requested")
            if aiRawWDMData is not None:
                aiFinalWDMData = processOutputArray(aiRawWDMData, pWDMProfile)

            if bProduceWSEMFile and 'aiRawWSEMData' in locals():
                aiFinalWSEMData = processOutputArray(aiRawWSEMData, pWSEMProfile)


        if aiFinalWDMData is not None:
            wasdi.wasdiLog("Saving final Water Depth Map")
            saveOutputWithNoData(sWDMPath, aiFinalWDMData, pWDMProfile, iPermanentWaterNoDataParam=iPermanentWaterAsNoData)

        if bProduceWSEMFile and aiFinalWSEMData is not None:
            wasdi.wasdiLog("Saving final Water Surface Elevation Map")
            saveOutputWithNoData(sWSEMPath, aiFinalWSEMData, pWSEMProfile, iPermanentWaterNoDataParam=iPermanentWaterAsNoData)


        # ---- 10. Cleanup ---- #
        if bDeleteConvertedFile and bThreeState:
            wasdi.deleteProduct(sProcessedFloodMapName)
        if bDeleteDEMFile and bGenerateDEM:
            wasdi.deleteProduct(sGeneratedDemFilename)

        wasdi.updateStatus("DONE", 100)
        wasdi.wasdiLog("Launcher app completed successfully")

    except Exception as oEx:
        wasdi.wasdiLog(f"Error in launcher app: {str(oEx)}")
        wasdi.updateStatus("ERROR", 0)
        return


if __name__ == '__main__':
    wasdi.init("./config.json")
    run()