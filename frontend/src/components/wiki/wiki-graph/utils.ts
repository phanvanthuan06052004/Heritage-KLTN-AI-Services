export function convexHull(points: [number, number][]): [number, number][] {
  if (points.length <= 1) return points;
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o: [number, number], a: [number, number], b: [number, number]) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: [number, number][] = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0)
      lower.pop();
    lower.push(p);
  }
  const upper: [number, number][] = [];
  for (const p of sorted.reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0)
      upper.pop();
    upper.push(p);
  }
  upper.pop();
  lower.pop();
  return lower.concat(upper);
}

export function hullToPath(hull: [number, number][], padding: number): string {
  if (hull.length === 0) return "";
  if (hull.length === 1) {
    const [x, y] = hull[0];
    return `M ${x - padding},${y} A ${padding},${padding} 0 1,0 ${x + padding},${y} A ${padding},${padding} 0 1,0 ${x - padding},${y} Z`;
  }
  if (hull.length === 2) {
    const [x1, y1] = hull[0];
    const [x2, y2] = hull[1];
    const dx = x2 - x1, dy = y2 - y1;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len * padding, ny = dx / len * padding;
    return `M ${x1 + nx},${y1 + ny} L ${x2 + nx},${y2 + ny} A ${padding},${padding} 0 0,1 ${x2 - nx},${y2 - ny} L ${x1 - nx},${y1 - ny} A ${padding},${padding} 0 0,1 ${x1 + nx},${y1 + ny} Z`;
  }
  const cx = hull.reduce((s, p) => s + p[0], 0) / hull.length;
  const cy = hull.reduce((s, p) => s + p[1], 0) / hull.length;
  const expanded = hull.map(([x, y]) => {
    const dx = x - cx, dy = y - cy;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    return [x + (dx / len) * padding, y + (dy / len) * padding] as [number, number];
  });
  const pts = expanded;
  const n = pts.length;
  let d = `M ${(pts[n - 1][0] + pts[0][0]) / 2},${(pts[n - 1][1] + pts[0][1]) / 2}`;
  for (let i = 0; i < n; i++) {
    const curr = pts[i];
    const next = pts[(i + 1) % n];
    const mx = (curr[0] + next[0]) / 2;
    const my = (curr[1] + next[1]) / 2;
    d += ` Q ${curr[0]},${curr[1]} ${mx},${my}`;
  }
  d += " Z";
  return d;
}

const SCOPE_COLORS = ["#7c8dac", "#9b8a6e", "#7a9e7a", "#b07a8a", "#8a7ab0", "#6e9b9b"];
export function scopeColor(idx: number): string {
  return SCOPE_COLORS[idx % SCOPE_COLORS.length];
}

export function nodeRadius(degree: number, mini: boolean): number {
  if (mini) return Math.max(3, Math.min(6, 3 + Math.sqrt(degree) * 1.2));
  return Math.max(5, Math.min(18, 5 + Math.sqrt(degree) * 3));
}
