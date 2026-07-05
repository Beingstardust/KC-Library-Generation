from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class KCLeafRaw:
    kc_id: str
    canonical_name: str
    kc_path: list[str]
    seed_definition: str
    aliases: list[str]


def _iter_kc_leaves(node: Any, path: list[str]) -> Iterator[tuple[list[str], dict[str, Any]]]:
    if not isinstance(node, dict):
        return

    if node.get("kc") is True:
        yield path, node
        return

    children = node.get("children")
    if isinstance(children, dict):
        for child_name, child_node in children.items():
            yield from _iter_kc_leaves(child_node, path + [str(child_name)])


def load_hierarchy_kcs(tree: dict[str, Any]) -> list[KCLeafRaw]:
    if not isinstance(tree, dict) or not tree:
        raise ValueError("Hierarchy must be a non-empty object at the root.")

    kcs: list[KCLeafRaw] = []

    for root_name, root_node in tree.items():
        for kc_path, leaf in _iter_kc_leaves(root_node, [str(root_name)]):
            canonical_name = kc_path[-1]
            kc_id = str(leaf.get("kc_id", "")).strip()
            seed_definition = str(leaf.get("definition", "")).strip()  # treat as seed_definition internally

            aliases = leaf.get("aliases", [])
            if aliases is None:
                aliases = []
            if not isinstance(aliases, list):
                aliases = [aliases]

            kcs.append(
                KCLeafRaw(
                    kc_id=kc_id,
                    canonical_name=canonical_name,
                    kc_path=kc_path,
                    seed_definition=seed_definition,
                    aliases=[str(a).strip() for a in aliases if str(a).strip()],
                )
            )

    return kcs