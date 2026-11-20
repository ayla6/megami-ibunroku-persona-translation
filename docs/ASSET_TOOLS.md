# Asset extraction

The contributor command uses the local disc and never downloads assets:

    python tools/extract_asset.py list-files
    python tools/extract_asset.py extract-file ADV/MES.BIN --output /tmp/MES.BIN
    python tools/extract_asset.py list-images ADV/BST.BIN
    python tools/extract_asset.py list-images ADV/MES.BIN --entry 11
    python tools/extract_asset.py export-image ADV/MES.BIN --entry 11 --member 1 --output /tmp/sheet.png

File commands accept --image PATH to use a particular MODE2/2352 BIN. Without
it they use the configured/discovered Rev 0 disc. Lists are TSV. File paths
come from the disc's directory; no manually maintained asset-name mapping is
required. Movie files retain raw sectors. Exports refuse to overwrite a file.

Image commands accept either an existing extracted file or its path beneath
data/psx. They list/export uncompressed 4/8/16bpp TIMs and TIMs inside a selected
MES scene entry. Member is the index printed by list-images; --offset 0x... can
select an explicit TIM instead. These commands do not decode every game-specific
inner format: models, animations and sound banks can be extracted as containing
files but still need their respective readers. Palette animation and alternate
CLUTs need explicit support beyond the default image export.

For a mod's already declared art, use the shared manifest exporter:

    python src/pipeline/image_replacements.py export black-mark --output /tmp/reference-art

Neither command creates previews during ordinary builds.
