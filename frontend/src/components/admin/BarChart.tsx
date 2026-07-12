// A dependency-free bar chart (CSS flex bars). Responsive by construction —
// bars flex to the container width. Values on hover (title); x-labels are shown
// sparsely so a 30-day series doesn't turn into unreadable mush.

export interface Bar {
  label: string;
  value: number;
}

interface BarChartProps {
  data: Bar[];
  color?: string;
  height?: number;
  formatValue?: (v: number) => string;
  /** Max number of x-axis labels to render (evenly spaced). */
  maxLabels?: number;
}

export function BarChart({
  data,
  color = "#4f46e5",
  height = 160,
  formatValue = (v) => v.toLocaleString(),
  maxLabels = 8,
}: BarChartProps) {
  if (data.length === 0) {
    return (
      <div
        style={{
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#888",
          fontSize: 13,
          border: "1px dashed #ddd",
          borderRadius: 6,
        }}
      >
        No data in range
      </div>
    );
  }

  const max = Math.max(...data.map((d) => d.value), 1);
  const labelStep = Math.max(1, Math.ceil(data.length / maxLabels));

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height }}>
      {data.map((d, i) => {
        const showLabel = i % labelStep === 0 || i === data.length - 1;
        return (
          <div
            key={`${d.label}-${i}`}
            title={`${d.label}: ${formatValue(d.value)}`}
            style={{
              flex: 1,
              minWidth: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "flex-end",
              height: "100%",
            }}
          >
            <div
              style={{
                width: "100%",
                height: `${(d.value / max) * 100}%`,
                minHeight: d.value > 0 ? 2 : 0,
                background: color,
                borderRadius: "3px 3px 0 0",
              }}
            />
            <span
              style={{
                fontSize: 9,
                lineHeight: "12px",
                marginTop: 4,
                color: "#666",
                whiteSpace: "nowrap",
                overflow: "hidden",
                height: 12,
              }}
            >
              {showLabel ? d.label : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
