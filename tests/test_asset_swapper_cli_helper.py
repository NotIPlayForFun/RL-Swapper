from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rl_swapper.backend.item_catalog import CatalogItem


def _install_swap_store_shims() -> None:
    import rl_swapper.backend.swap_store as swap_store

    for name in ("list_swaps", "load_swap_manifest", "mark_swap_pushed", "mark_swap_unpushed", "save_swap_manifest"):
        if not hasattr(swap_store, name):
            setattr(swap_store, name, lambda *args, **kwargs: None)


_install_swap_store_shims()

from rl_swapper.backend.swap_orchestration.swap_orchestration import _asset_swapper_cli_helper


def _make_item(item_id: int, asset_package: str = "example.upk") -> CatalogItem:
    return CatalogItem(
        item_id=item_id,
        asset_package=asset_package,
        asset_path="Package.Asset",
        product="Example",
        quality="",
        slot="",
        unlock_method="",
    )


def test_normal_execution_branch() -> None:
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        items_path = base / "items.json"
        items_path.write_text("[]", encoding="utf-8")
        source_donor_dir = base / "donor"
        output_target_dir = base / "output"
        source_target_dir = base / "target"
        work_dir = base / "work"
        keys_path = base / "keys.txt"
        keys_map_path = base / "keys_map.json"

        donor = _make_item(1001, "donor.upk")
        target = _make_item(2002, "target.upk")

        recorded = {}

        def fake_run(command, cwd, check, capture_output, text):
            recorded["command"] = command
            recorded["cwd"] = cwd
            recorded["check"] = check
            recorded["capture_output"] = capture_output
            recorded["text"] = text

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch.object(sys, "frozen", False, create=True), patch.object(sys, "executable", "C:/Python/python.exe"), patch("rl_swapper.backend.swap_orchestration.swap_orchestration.subprocess.run", side_effect=fake_run):
            _asset_swapper_cli_helper(
                items_path=items_path,
                source_donor_dir=source_donor_dir,
                output_target_dir=output_target_dir,
                source_target_dir=source_target_dir,
                work_dir=work_dir,
                target=target,
                donor=donor,
                with_thumbnails=False,
                target_thumb_name=None,
                donor_thumb_name=None,
                keys_path=keys_path,
                keys_map_path=keys_map_path,
            )

        assert recorded["cwd"] == work_dir
        assert recorded["check"] is False
        assert recorded["capture_output"] is True
        assert recorded["text"] is True
        assert recorded["command"][:3] == ["C:/Python/python.exe", "-m", "rl_swapper.backend.engine.rl_asset_swapper"]
        assert "--no-thumbnails" in recorded["command"]
        assert "--include-thumbnails" not in recorded["command"]
        assert recorded["command"].count("--keys") == 1
        assert recorded["command"].count("--keys-map") == 1


def test_frozen_execution_branch() -> None:
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        items_path = base / "items.json"
        items_path.write_text("[]", encoding="utf-8")
        source_donor_dir = base / "donor"
        output_target_dir = base / "output"
        source_target_dir = base / "target"
        work_dir = base / "work"
        keys_path = base / "keys.txt"
        keys_map_path = base / "keys_map.json"

        donor = _make_item(3003, "donor.upk")
        target = _make_item(4004, "target.upk")

        import rl_swapper.backend.engine.rl_asset_swapper as swapper_module

        seen = {}

        class DummyParser:
            def parse_args(self, args):
                seen["args"] = list(args)
                return {"parsed": True}

        def fake_cli_run(parsed_args):
            seen["parsed_args"] = parsed_args
            return 0

        with patch.object(sys, "frozen", True, create=True), patch.object(swapper_module, "build_arg_parser", return_value=DummyParser()), patch.object(swapper_module, "cli_run", side_effect=fake_cli_run):
            _asset_swapper_cli_helper(
                items_path=items_path,
                source_donor_dir=source_donor_dir,
                output_target_dir=output_target_dir,
                source_target_dir=source_target_dir,
                work_dir=work_dir,
                target=target,
                donor=donor,
                with_thumbnails=True,
                target_thumb_name=None,
                donor_thumb_name=None,
                keys_path=keys_path,
                keys_map_path=keys_map_path,
            )

        assert seen["parsed_args"] == {"parsed": True}
        assert seen["args"][0:3] == ["--items", str(items_path), "--donor-dir"]
        assert "--include-thumbnails" in seen["args"]
        assert "--no-thumbnails" not in seen["args"]
        assert "--keys" in seen["args"]
        assert "--keys-map" in seen["args"]


if __name__ == "__main__":
    test_normal_execution_branch()
    test_frozen_execution_branch()
    print("ok")