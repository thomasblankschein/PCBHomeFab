import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from pcbhomefab import cli, pm3
from pcbhomefab.board import load_board
from pcbhomefab.mask import build_mask
from pcbhomefab.panel import pack
from pcbhomefab.profiles import PHOTON_M3, Plate

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def mask() -> Image.Image:
    base = load_board(DATA / "basisplatine.zip")
    return build_mask(pack([base], Plate()), PHOTON_M3)


def test_layer_encoding_round_trip() -> None:
    image = Image.new("L", (64, 32), 0)
    image.paste(255, (10, 4, 50, 20))
    encoded, white = pm3.encode_layer(image)
    assert white == 40 * 16
    decoded = pm3.decode_layer(encoded, 64, 32)
    assert ImageChops.difference(decoded, image).getbbox() is None


def test_long_runs_are_split() -> None:
    image = Image.new("L", (100, 100), 255)  # 10,000 white pixels need three runs of at most 4095
    encoded, white = pm3.encode_layer(image)
    assert white == 10_000
    assert len(encoded) == 3 * 2
    assert pm3.decode_layer(encoded, 100, 100).getextrema() == (255, 255)


def test_write_and_read_back(tmp_path: Path, mask: Image.Image) -> None:
    target = tmp_path / "mask.pm3"
    pm3.write_pm3(mask, PHOTON_M3, target, exposure_s=90)
    info = pm3.read_pm3(target)
    assert info.machine_name == "Anycubic Photon M3"
    assert info.resolution == (4096, 2560)
    assert (info.exposure_s, info.bottom_exposure_s, info.layer_count) == (90.0, 90.0, 1)
    assert ImageChops.difference(info.first_layer, mask.convert("L")).getbbox() is None


def test_machine_table_equals_photon_workshop(mask: Image.Image) -> None:
    """Without a template the MACHINE table must match the one Photon Workshop wrote for the M3."""
    data = pm3.build_pm3(mask, PHOTON_M3)
    start = data.find(b"MACHINE" + bytes([0]))
    assert data[start : start + pm3.MACHINE_TABLE_SIZE] == (DATA / "photon_m3_machine_table.bin").read_bytes()


def test_several_layers(tmp_path: Path, mask: Image.Image) -> None:
    target = tmp_path / "three.pm3"
    pm3.write_pm3(mask, PHOTON_M3, target, layers=3)
    info = pm3.read_pm3(target)
    assert info.layer_count == 3
    assert info.bottom_layers == 3


def test_template_parameters_are_taken_over(tmp_path: Path, mask: Image.Image) -> None:
    from dataclasses import replace

    other = replace(PHOTON_M3, lift_height_mm=8.0, lift_speed_mms=2.0, retract_speed_mms=5.0)
    template = tmp_path / "template.pm3"
    pm3.write_pm3(mask, other, template)
    target = tmp_path / "out.pm3"
    pm3.write_pm3(mask, PHOTON_M3, target, template=template)
    info = pm3.read_pm3(target)
    assert (info.lift_height_mm, info.lift_speed_mms, info.retract_speed_mms) == (8.0, 2.0, 5.0)


def test_rejects_wrong_mask_size(tmp_path: Path) -> None:
    with pytest.raises(pm3.Pm3Error):
        pm3.write_pm3(Image.new("1", (100, 100)), PHOTON_M3, tmp_path / "x.pm3")


def test_rejects_foreign_file(tmp_path: Path) -> None:
    junk = tmp_path / "junk.pm3"
    junk.write_bytes(b"not an anycubic file")
    with pytest.raises(pm3.Pm3Error):
        pm3.read_pm3(junk)


def _uvtools() -> str | None:
    found = shutil.which("UVtoolsCmd")
    if found:
        return found
    default = Path(r"C:\Program Files\UVtools\UVtoolsCmd.exe")
    return str(default) if default.exists() else None


@pytest.mark.skipif(_uvtools() is None, reason="UVtools is not installed")
def test_uvtools_reads_the_file(tmp_path: Path, mask: Image.Image) -> None:
    """Cross-check with an independent implementation of the format."""
    uvtools = _uvtools()
    assert uvtools is not None
    target = tmp_path / "mask.pm3"
    pm3.write_pm3(mask, PHOTON_M3, target, exposure_s=90)
    props = subprocess.run(
        [uvtools, "print-properties", str(target)], capture_output=True, text=True, check=True
    )
    assert "MachineName: Anycubic Photon M3" in props.stdout
    assert "ExposureTime: 90" in props.stdout
    assert "ResolutionX: 4096" in props.stdout
    folder = tmp_path / "extracted"
    subprocess.run([uvtools, "extract", str(target), str(folder)], capture_output=True, check=True)
    layer = Image.open(folder / "layer0.png").convert("L")
    assert ImageChops.difference(layer, mask.convert("L")).getbbox() is None


def test_cli_exposure_and_mill(tmp_path: Path) -> None:
    node = str(DATA / "fuehlerknoten.zip")
    assert cli.main(["exposure", f"{node}:3", "-o", str(tmp_path), "--name", "t", "--pm3"]) == 0
    assert (tmp_path / "t.png").exists()
    assert pm3.read_pm3(tmp_path / "t.pm3").layer_count == 1
    assert cli.main(["mill", f"{node}:3", "-o", str(tmp_path), "--name", "t"]) == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "t_1_drill_0.8mm.nc" in names and "t_preview.svg" in names


def test_cli_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "x.zip"
    broken.write_bytes(b"nope")
    assert cli.main(["exposure", str(broken), "-o", str(tmp_path)]) == 1
    assert "Error:" in capsys.readouterr().err
