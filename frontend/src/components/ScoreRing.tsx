export function ScoreRing({ score, color, size = 168, label }: { score: number | null; color: string; size?: number; label?: string }) {
  const stroke = 14
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`身体状态 ${score ?? '—'} / 100`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-2)" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${c * pct} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="47%" textAnchor="middle" dominantBaseline="middle" fontSize={size * 0.27} fontWeight={700} fill="var(--text)">
        {score === null ? '—' : Math.round(score)}
      </text>
      <text x="50%" y="66%" textAnchor="middle" fontSize={12} fill="var(--muted)">
        {label ?? '/ 100'}
      </text>
    </svg>
  )
}
