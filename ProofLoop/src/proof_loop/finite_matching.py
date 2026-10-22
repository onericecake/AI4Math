"""Exact, bounded bipartite matching for explicit finite instances.

This module accepts data, never executable model-supplied code. A failed
matching includes a Hall witness that can be checked from the input graph.
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any


MAX_INSTANCES = 32
MAX_SIDE = 128
MAX_EDGES = 8192
MAX_TOTAL_EDGES = 32768


def _labels(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_SIDE or any(not isinstance(x, str) or not x or len(x) > 120 for x in value):
        raise ValueError(f"{field} must be a list of at most {MAX_SIDE} nonempty string labels")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} contains duplicate labels")
    return value


def _parse_instance(raw: Any) -> tuple[str, list[str], list[str], list[list[int]]]:
    if not isinstance(raw, dict) or set(raw) != {"name", "left", "right", "edges"}:
        raise ValueError("each matching instance needs exactly name, left, right, and edges")
    name = raw["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("instance name must be a nonempty string of at most 120 characters")
    left = _labels(raw["left"], "left")
    right = _labels(raw["right"], "right")
    edges = raw["edges"]
    if not isinstance(edges, list) or len(edges) > MAX_EDGES:
        raise ValueError(f"edges must be a list of at most {MAX_EDGES} pairs")
    left_at = {label: index for index, label in enumerate(left)}
    right_at = {label: index for index, label in enumerate(right)}
    adjacency: list[list[int]] = [[] for _ in left]
    seen: set[tuple[int, int]] = set()
    for edge in edges:
        if not isinstance(edge, list) or len(edge) != 2 or any(not isinstance(x, str) for x in edge):
            raise ValueError("each edge must be a two-label list [left, right]")
        if edge[0] not in left_at or edge[1] not in right_at:
            raise ValueError("edge refers to a label outside its side")
        pair = (left_at[edge[0]], right_at[edge[1]])
        if pair in seen:
            raise ValueError("duplicate matching edge")
        seen.add(pair)
        adjacency[pair[0]].append(pair[1])
    return name, left, right, adjacency


def _maximum_matching(adjacency: list[list[int]], right_count: int, deadline: float) -> tuple[list[int], list[int]]:
    """Hopcroft-Karp; returned arrays contain the mate index or -1."""
    left_count = len(adjacency)
    left_mate = [-1] * left_count
    right_mate = [-1] * right_count
    distance = [0] * left_count

    def augment(left: int) -> bool:
        for right in adjacency[left]:
            mate = right_mate[right]
            if mate < 0 or (distance[mate] == distance[left] + 1 and augment(mate)):
                left_mate[left] = right
                right_mate[right] = left
                return True
        distance[left] = -1
        return False

    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("finite matching time limit reached")
        queue = deque()
        for left in range(left_count):
            distance[left] = 0 if left_mate[left] < 0 else -1
            if left_mate[left] < 0:
                queue.append(left)
        found = False
        while queue:
            left = queue.popleft()
            for right in adjacency[left]:
                mate = right_mate[right]
                if mate < 0:
                    found = True
                elif distance[mate] < 0:
                    distance[mate] = distance[left] + 1
                    queue.append(mate)
        if not found:
            break
        for left in range(left_count):
            if left_mate[left] < 0:
                augment(left)
    return left_mate, right_mate


def _hall_witness(adjacency: list[list[int]], left_mate: list[int], right_mate: list[int]) -> tuple[list[int], list[int]]:
    """Alternating reachability from unmatched left vertices gives S, N(S)."""
    seen_left = {left for left, mate in enumerate(left_mate) if mate < 0}
    seen_right: set[int] = set()
    queue = deque(seen_left)
    while queue:
        left = queue.popleft()
        for right in adjacency[left]:
            if right in seen_right:
                continue
            seen_right.add(right)
            mate = right_mate[right]
            if mate >= 0 and mate not in seen_left:
                seen_left.add(mate)
                queue.append(mate)
    assert len(seen_right) < len(seen_left)
    assert seen_right == {right for left in seen_left for right in adjacency[left]}
    return sorted(seen_left), sorted(seen_right)


def check_matching(code: str, seconds: float) -> dict[str, Any]:
    """Check a JSON batch of explicit finite bipartite graphs."""
    start = time.monotonic()
    try:
        document = json.loads(code)
        if not isinstance(document, dict) or set(document) != {"instances"}:
            raise ValueError("matching input must be a JSON object with only an instances array")
        instances = document["instances"]
        if not isinstance(instances, list) or not 1 <= len(instances) <= MAX_INSTANCES:
            raise ValueError(f"instances must contain between 1 and {MAX_INSTANCES} graphs")
        parsed = [_parse_instance(item) for item in instances]
        if len({item[0] for item in parsed}) != len(parsed):
            raise ValueError("instance names must be distinct")
        if sum(sum(map(len, item[3])) for item in parsed) > MAX_TOTAL_EDGES:
            raise ValueError(f"batch has more than {MAX_TOTAL_EDGES} edges")
        deadline = start + max(0.001, seconds)
        results = []
        for name, left, right, adjacency in parsed:
            left_mate, right_mate = _maximum_matching(adjacency, len(right), deadline)
            size = sum(mate >= 0 for mate in left_mate)
            result: dict[str, Any] = {"name": name, "left_count": len(left), "right_count": len(right),
                                      "edge_count": sum(map(len, adjacency)), "maximum_matching_size": size,
                                      "all_left_matched": size == len(left),
                                      "matching": [[left[i], right[mate]] for i, mate in enumerate(left_mate) if mate >= 0]}
            if size < len(left):
                witness_left, witness_right = _hall_witness(adjacency, left_mate, right_mate)
                result["hall_witness"] = {"left": [left[i] for i in witness_left],
                                          "neighbors": [right[i] for i in witness_right],
                                          "deficiency": len(witness_left) - len(witness_right)}
            results.append(result)
        return {"status": "completed", "seconds": round(time.monotonic() - start, 3),
                "output": json.dumps({"cases": results}, ensure_ascii=False),
                "evidence_only": True, "runtime": "builtin:matching"}
    except TimeoutError as error:
        return {"status": "timed_out", "seconds": round(time.monotonic() - start, 3),
                "output": str(error), "evidence_only": True, "runtime": "builtin:matching"}
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        return {"status": "failed", "seconds": round(time.monotonic() - start, 3),
                "output": f"Invalid matching input: {error}", "evidence_only": True, "runtime": "builtin:matching"}
