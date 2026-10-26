import struct
import subprocess
from pathlib import Path

import pytest

from pcbhomefab import cli, pm3
from pcbhomefab.board import load_board
from pcbhomefab.mask import build_mask
from pcbhomefab.panel import pack
from pcbhomefab.profiles import PHOTON_M3, Plate

DATA = Path(__file__).parent / "data"


def _fake_pm3(name: bytes = b"Unknown") -> bytes:
    """Minimal bytes with a MACHINE table at the layout of a real .pm3 file."""
    table = bytearray(pm3.MACHINE_TABLE_SIZE)
    table[0:8] = b"MACHINE" + bytes([0])
    struct.pack_into("<I", table, 12, pm3.MACHINE_TABLE_SIZE)
    table[16 : 16 + len(name)] = name
    struct.pack_into("<f", table, 144, 0.05)
    return b"ANYCUBIC" + bytes(40) + bytes(table) + bytes(16)


def test_set_machine_patches_name_and_height(tmp_path: Path) -> None:
    target = tmp_path / "a.pm3"
    target.write_bytes(_fake_pm3())
    pm3.set_machine(target, "Anycubic Photon M3", 180.0)
    data = target.read_bytes()
    start = data.find(b"MACHINE" + bytes([0]))
    assert data[start + 16 : start + 112].split(bytes([0]))[0] == b"Anycubic Photon M3"
    assert struct.unpack_from("<f", data, start + 144)[0] == 180.0
    assert len(data) == len(_fake_pm3())


def test_copy_machine_table(tmp_path: Path) -> None:
    target, template = tmp_path / "a.pm3", tmp_path / "t.pm3"
    target.write_bytes(_fake_pm3())
    template.write_bytes(_fake_pm3(b"Reference Printer"))
    pm3.copy_machine_table(target, template)
    assert b"Reference Printer" in target.read_bytes()


def test_set_machine_rejects_unknown_format(tmp_path: Path) -> None:
    target = tmp_path / "a.pm3"
    target.write_bytes(b"not a pm3 file")
    with pytest.raises(pm3.UVtoolsError):
        pm3.set_machine(target, "x", 180.0)


def _uvtools_available() -> bool:
    try:
        pm3.find_uvtools()
    except pm3.UVtoolsError:
        return False
    return True


@pytest.mark.skipif(not _uvtools_available(), reason="UVtools is not installed")
def test_write_pm3_with_uvtools(tmp_path: Path) -> None:
    base = load_board(DATA / "basisplatine.zip")
    mask = build_mask(pack([base], Plate()), PHOTON_M3)
    target = tmp_path / "mask.pm3"
    pm3.write_pm3(mask, PHOTON_M3, target, exposure_s=90)
    result = subprocess.run(
        [str(pm3.find_uvtools()), "print-properties", str(target)], capture_output=True, text=True, check=True
    )
    assert "MachineName: Anycubic Photon M3" in result.stdout
    assert "ExposureTime: 90" in result.stdout
    assert "ResolutionX: 4096" in result.stdout


def test_cli_exposure_and_mill(tmp_path: Path) -> None:
    node = str(DATA / "fuehlerknoten.zip")
    assert cli.main(["exposure", f"{node}:3", "-o", str(tmp_path), "--name", "t"]) == 0
    assert (tmp_path / "t.png").exists()
    assert cli.main(["mill", f"{node}:3", "-o", str(tmp_path), "--name", "t"]) == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "t_1_drill_0.8mm.nc" in names and "t_preview.svg" in names


def test_cli_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "x.zip"
    broken.write_bytes(b"nope")
    assert cli.main(["exposure", str(broken), "-o", str(tmp_path)]) == 1
    assert "Error:" in capsys.readouterr().err
