/**
 * sgs-ui-2hf: drop preset-author-hidden nodes from a ComfyGen block
 * auto-detection array.
 *
 * Preset authors can set `workflows[].hidden_nodes: ["77", "123"]` to
 * suppress specific workflow nodes from showing up in the auto-detected
 * panels (KSampler / LoRA / Resolution / Frame / RefVideo / LoadNode /
 * Text override). The hidden nodes still execute with whatever values
 * the workflow JSON ships — they just don't get a UI knob.
 *
 * Extracted as a pure helper so the filter is unit-testable without
 * mounting the 2,500-line ComfyGen component.
 */

/** Build a Set of stringified node IDs from a preset's hidden_nodes list. */
export function hiddenSetFrom(hidden: string[] | undefined): Set<string> {
  if (!hidden || hidden.length === 0) return new Set()
  return new Set(hidden.map((n) => String(n)))
}

/**
 * Filter out entries whose `node_id` matches an id in `hidden`.
 * Coerces each item's `node_id` to a string before comparing (some
 * detection arrays may carry numeric IDs through).
 */
export function dropHidden<T extends { node_id: string }>(
  arr: T[],
  hidden: Set<string>,
): T[] {
  if (hidden.size === 0) return arr
  return arr.filter((item) => !hidden.has(String(item.node_id)))
}
