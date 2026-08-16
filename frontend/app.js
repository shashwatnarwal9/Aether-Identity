/* Shared data layer + helpers for the Aether Identity pages. React UMD, no build step. */
const h = React.createElement;

const api = (path, opts) => fetch(path, opts).then(r => {
  if (!r.ok && r.status !== 409 && r.status !== 422) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
});

/* Strategy metadata: engine strategy -> display name + status chip (colors from the Stitch design). */
const STRATEGIES = {
  edge_biometric_priority: { label: "Biometric Similarity Match", status: "Verified",
    icon: "check_circle", chip: "bg-signal-teal/10 text-signal-teal border-signal-teal/20", bar: "bg-signal-teal" },
  mobile_device_priority: { label: "Device Fingerprint Overlap", status: "Resolved",
    icon: "merge", chip: "bg-electric-blue/10 text-electric-blue border-electric-blue/20", bar: "bg-electric-blue" },
  web_behavior_priority: { label: "Behavioral Telemetry Match", status: "Resolved",
    icon: "merge", chip: "bg-electric-blue/10 text-electric-blue border-electric-blue/20", bar: "bg-electric-blue" },
  deterministic_fallback: { label: "Temporal Proximity Reconcile", status: "Resolved",
    icon: "merge", chip: "bg-cyber-purple/10 text-cyber-purple border-cyber-purple/20", bar: "bg-cyber-purple" },
  new_identity: { label: "New Identity Registered", status: "Verified",
    icon: "check_circle", chip: "bg-signal-teal/10 text-signal-teal border-signal-teal/20", bar: "bg-signal-teal" },
  same_user_append: { label: "Same User Append", status: "Verified",
    icon: "check_circle", chip: "bg-signal-teal/10 text-signal-teal border-signal-teal/20", bar: "bg-signal-teal" },
  rejected: { label: "Validation / Late Rejection", status: "Rejected",
    icon: "block", chip: "bg-error/10 text-error border-error/20", bar: "bg-error" },
  duplicate: { label: "Duplicate Event", status: "Duplicate",
    icon: "content_copy", chip: "bg-outline/10 text-on-surface-variant border-outline/20", bar: "bg-outline" },
};
const strategyMeta = s => STRATEGIES[s] || STRATEGIES.deterministic_fallback;

/* Platform metadata (mobile indigo / web orange / edge teal — as used across the Stitch screens). */
const PLATFORMS = {
  mobile: { name: "Mobile App", icon: "smartphone", color: "#4648d4",
    chip: "bg-primary/10 text-primary", box: "bg-electric-blue/10 text-electric-blue border-electric-blue/20" },
  web: { name: "Web Portal", icon: "language", color: "#ea580c",
    chip: "bg-orange-500/10 text-orange-600", box: "bg-orange-500/10 text-orange-600 border-orange-500/20" },
  edge: { name: "Edge Device", icon: "router", color: "#00687a",
    chip: "bg-secondary/10 text-secondary", box: "bg-secondary/10 text-secondary border-secondary/20" },
};
const platformMeta = p => PLATFORMS[p] || { name: p, icon: "device_unknown", color: "#767586",
  chip: "bg-surface-container text-on-surface-variant", box: "bg-surface-container text-on-surface-variant border-outline-variant/30" };

const fmtTs = t => t ? t.replace(/\.\d+\+00:00$/, "Z").replace("T", " ") : "—";
const shortTs = t => t ? t.replace(/\.\d+\+00:00$/, "Z") : "—";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const scrubTs = t => {  // "Aug 10, 09:00Z" like the design's scrubber labels
  if (!t) return "—";
  const d = new Date(t);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ` +
    `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}Z`;
};

const eventDesc = e => {
  if (e.embedding) return `Face Embeddings (ONNX)${e.confidence != null ? ` · ${e.confidence} Conf` : ""}`;
  if (e.behavior_data) return "Behavioral Telemetry: " +
    Object.entries(e.behavior_data).map(([k, v]) => `${k}=${v}`).join(", ");
  if (e.confidence != null) return `Match Result: ${e.confidence} Conf`;
  return `Login · device ${e.device_id}`;
};

/* Compact JSON for event cards: summarize the 128-dim embedding. */
const eventJson = e => JSON.stringify(
  { ...e, embedding: e.embedding ? `<${e.embedding.length}-dim vector>` : undefined },
  null, 2);

const icon = (name, cls) => h("span", { className: "material-symbols-outlined " + (cls || "") }, name);
