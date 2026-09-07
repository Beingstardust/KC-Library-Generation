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


# Real, checkable contract (confirmed against every downstream consumer - see
# ORCHESTRATOR_BUILD_STATE.md's hierarchy-ingestion-robustness investigation entry): a KC leaf
# is identified structurally (no children), not by a manually-set "kc": true marker - a
# hierarchy author naturally knows a node is a leaf without needing to also remember a separate
# flag. "kc": true is no longer read here at all; a node with no children IS a KC leaf,
# unconditionally. The only genuinely required datum is kc_id - canonical_name is already
# satisfiable structurally (the node's own key in its parent's children dict), and
# seed_definition/aliases remain optional everywhere downstream (confirmed: validate_kc_leaves
# only WARNs on missing seed_definition, never ERRORs).
KC_ID_KEYS: tuple[str, ...] = ("kc_id", "id")
CANONICAL_NAME_KEYS: tuple[str, ...] = ("canonical_name", "name", "label")


def _first_present(node: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(node.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _iter_kc_leaves(node: Any, path: list[str]) -> Iterator[tuple[list[str], dict[str, Any]]]:
    if not isinstance(node, dict):
        return

    children = node.get("children")
    if isinstance(children, dict) and children:
        for child_name, child_node in children.items():
            yield from _iter_kc_leaves(child_node, path + [str(child_name)])
        return

    # Structurally terminal (no children) - this is a KC leaf, regardless of any marker flag.
    yield path, node


def load_hierarchy_kcs(tree: dict[str, Any]) -> list[KCLeafRaw]:
    if not isinstance(tree, dict) or not tree:
        raise ValueError("Hierarchy must be a non-empty object at the root.")

    kcs: list[KCLeafRaw] = []

    for root_name, root_node in tree.items():
        for kc_path, leaf in _iter_kc_leaves(root_node, [str(root_name)]):
            kc_id = _first_present(leaf, KC_ID_KEYS)
            canonical_name = _first_present(leaf, CANONICAL_NAME_KEYS) or kc_path[-1]
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
