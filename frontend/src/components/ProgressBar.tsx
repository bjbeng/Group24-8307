export default function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div style={{ background: "#e5e7eb", borderRadius: 8, height: 12, overflow: "hidden" }}>
      <div style={{ width: `${pct}%`, background: "#2563eb", height: "100%", transition: "width 0.3s" }} />
    </div>
  );
}
