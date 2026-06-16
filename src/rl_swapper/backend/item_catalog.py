#!/usr/bin/env python3
"""Item catalog helpers for Rocket League UPK swapping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ItemRecord:
    item_id: int
    asset_package: str
    asset_path: str
    product: str
    quality: str
    slot: str
    unlock_method: str


def normalize_query(value: str) -> str:
    return value.strip().lower()


def stem_matches(asset_package: str, file_name: str) -> bool:
    return Path(asset_package).name == Path(file_name).name


def load_items(items_path: Path) -> list[ItemRecord]:
    data = json.loads(items_path.read_text(encoding="utf-8-sig"))
    rows = data.get("Items") or data.get("items") or []
    items: list[ItemRecord] = []
    for row in rows:
        asset_package = str(row.get("AssetPackage") or row.get("asset_package") or "")
        if not asset_package:
            continue
        try:
            item_id = int(row.get("ID") or row.get("id") or 0)
        except Exception:
            continue
        items.append(
            ItemRecord(
                item_id=item_id,
                asset_package=asset_package,
                asset_path=str(row.get("AssetPath") or row.get("asset_path") or ""),
                product=str(row.get("Product") or row.get("label") or row.get("long_label") or ""),
                quality=str(row.get("Quality") or row.get("quality") or ""),
                slot=str(row.get("Slot") or row.get("slot") or ""),
                unlock_method=str(row.get("UnlockMethod") or row.get("unlock_method") or ""),
            )
        )
    return items


def item_matches(item: ItemRecord, query: str) -> bool:
    if not query:
        return True
    haystacks = (
        item.product,
        item.asset_package,
        item.asset_path,
        item.quality,
        item.slot,
        item.unlock_method,
        str(item.item_id),
    )
    return any(query in str(haystack).lower() for haystack in haystacks)


def search_items(items: list[ItemRecord], query: str) -> list[ItemRecord]:
    normalized = normalize_query(query)
    matches = [item for item in items if item_matches(item, normalized)]
    return sorted(matches, key=lambda item: (item.product.lower(), item.asset_package.lower(), item.item_id))


def find_item_by_product(product: str, items: list[ItemRecord]) -> ItemRecord:
    normalized = normalize_query(product)
    exact_matches = [item for item in items if normalize_query(item.product) == normalized]
    if len(exact_matches) == 1:
        return exact_matches[0]
    partial_matches = [item for item in items if normalized and normalized in normalize_query(item.product)]
    if len(partial_matches) == 1:
        return partial_matches[0]
    if exact_matches or partial_matches:
        options = exact_matches or partial_matches
        listed = ", ".join(option.product for option in options[:5])
        raise SystemExit(f"Product lookup for {product!r} matched multiple items: {listed}")
    raise SystemExit(f"No item found for product {product!r}")


def find_item_id(file_name: str, items: list[ItemRecord]) -> int:
    normalized = Path(file_name).name
    for item in items:
        if stem_matches(item.asset_package, normalized):
            return item.item_id
    raise SystemExit(f"No item database entry found for {file_name!r} in python/items.json")


def find_item_by_filename(file_name: str, items: list[ItemRecord]) -> ItemRecord:
    normalized = Path(file_name).name
    for item in items:
        if stem_matches(item.asset_package, normalized):
            return item
    raise SystemExit(f"No item database entry found for {file_name!r} in python/items.json")
