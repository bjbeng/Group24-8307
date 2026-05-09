import { useI18n } from "../i18n/I18nContext";

interface DonutChartProps {
  high: number;
  medium: number;
  low: number;
  size?: number;
}

function DonutChart({ high, medium, low, size = 56 }: DonutChartProps) {
  const { t } = useI18n();
  const total = high + medium + low;
  const outerR = 22;
  const innerR = 12;
  const cx = 28;
  const cy = 28;

  if (total === 0) {
    return (
      <div style={{ position: "relative", width: size, height: size }}>
        <svg width={size} height={size} viewBox="0 0 56 56">
          <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="#f1f5f9" strokeWidth="7" />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <span style={{ fontSize: 12, fontWeight: 800, color: "#9ca3af" }}>0</span>
          <span style={{ fontSize: 7, color: "#94a3b8" }}>{t.items}</span>
        </div>
      </div>
    );
  }

  const C = 2 * Math.PI * outerR;
  const highLen = (high / total) * C;
  const medLen = (medium / total) * C;
  const lowLen = (low / total) * C;

  const startOffset = C / 4;
  const highOffset = startOffset;
  const medOffset = startOffset + highLen;
  const lowOffset = startOffset + highLen + medLen;

  const renderFullCircle = highLen >= C - 0.1 || medLen >= C - 0.1 || lowLen >= C - 0.1;

  // 扇区中心点角度（用于放置标签）
  function midAngle(startLen: number, dashLen: number): number {
    return startOffset + startLen + dashLen / 2;
  }

  const highMid = midAngle(0, highLen);
  const medMid = midAngle(highLen, medLen);
  const lowMid = midAngle(highLen + medLen, lowLen);

  // 将角度转为 SVG 圆弧上点的坐标
  function labelPos(angle: number, r: number): { x: number; y: number } {
    // SVG 角度：0° 在 3点钟，顺时针为正
    const rad = angle;
    return {
      x: cx + r * Math.cos(rad - Math.PI / 2),
      y: cy + r * Math.sin(rad - Math.PI / 2),
    };
  }

  const highLabel = labelPos(highMid, outerR + 10);
  const medLabel = labelPos(medMid, outerR + 10);
  const lowLabel = labelPos(lowMid, outerR + 10);

  const showLabel = (count: number) => count > 0 && total > 1;

  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 56 56">
        {/* 背景灰色环 */}
        <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="#f1f5f9" strokeWidth="7" />

        {renderFullCircle ? (
          highLen >= C - 0.1 ? (
            <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="#dc2626" strokeWidth="7" strokeDasharray={`${C} ${C}`} strokeDashoffset={0} strokeLinecap="butt" />
          ) : medLen >= C - 0.1 ? (
            <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="#d97706" strokeWidth="7" strokeDasharray={`${C} ${C}`} strokeDashoffset={0} strokeLinecap="butt" />
          ) : (
            <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="#16a34a" strokeWidth="7" strokeDasharray={`${C} ${C}`} strokeDashoffset={0} strokeLinecap="butt" />
          )
        ) : (
          <>
            {highLen > 0 && (
              <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="#dc2626" strokeWidth="7"
                strokeDasharray={`${highLen} ${C - highLen}`} strokeDashoffset={C - highOffset} strokeLinecap="butt" />
            )}
            {medLen > 0 && (
              <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="#d97706" strokeWidth="7"
                strokeDasharray={`${medLen} ${C - medLen}`} strokeDashoffset={C - medOffset} strokeLinecap="butt" />
            )}
            {lowLen > 0 && (
              <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="#16a34a" strokeWidth="7"
                strokeDasharray={`${lowLen} ${C - lowLen}`} strokeDashoffset={C - lowOffset} strokeLinecap="butt" />
            )}
          </>
        )}

        {/* 各段数量标签 */}
        {showLabel(high) && (
          <text x={highLabel.x} y={highLabel.y} textAnchor="middle" dominantBaseline="middle"
            style={{ fontSize: 8, fontWeight: 700, fill: "#dc2626" }}>{high}</text>
        )}
        {showLabel(medium) && (
          <text x={medLabel.x} y={medLabel.y} textAnchor="middle" dominantBaseline="middle"
            style={{ fontSize: 8, fontWeight: 700, fill: "#d97706" }}>{medium}</text>
        )}
        {showLabel(low) && (
          <text x={lowLabel.x} y={lowLabel.y} textAnchor="middle" dominantBaseline="middle"
            style={{ fontSize: 8, fontWeight: 700, fill: "#16a34a" }}>{low}</text>
        )}
      </svg>

      {/* 中心：总数 + 标签 */}
      <div style={{
        position: "absolute", top: "50%", left: "50%",
        transform: "translate(-50%,-50%)",
        width: innerR * 2, height: innerR * 2, borderRadius: "50%",
        background: "#fff",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
      }}>
        <span style={{ fontSize: 12, fontWeight: 800, color: "#1e293b" }}>{total}</span>
        <span style={{ fontSize: 7, color: "#94a3b8", marginTop: 1 }}>{t.items}</span>
      </div>
    </div>
  );
}

export default DonutChart;
