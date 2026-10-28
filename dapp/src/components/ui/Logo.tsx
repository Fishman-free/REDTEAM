export function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
    >
      <path d="M3 12V3h9" stroke="currentColor" strokeWidth="1.6" />
      <path d="M37 12V3h-9" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3 28v9h9" stroke="currentColor" strokeWidth="1.6" />
      <path d="M37 28v9h-9" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="20" cy="20" r="8.5" stroke="currentColor" strokeWidth="1.2" opacity=".55" />
      <circle cx="20" cy="20" r="2.4" fill="currentColor" />
      <path d="M20 5v7M20 28v7M5 20h7M28 20h7" stroke="currentColor" strokeWidth="1.1" opacity=".7" />
    </svg>
  );
}

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`wordmark ${compact ? "wordmark--compact" : ""}`.trim()}>
      <BrandMark size={compact ? 26 : 32} />
      <span className="wordmark__text">
        <span className="wordmark__name">
          RTM<span className="wordmark__slash">//</span>
          <span className="wordmark__accent">ARENA</span>
        </span>
        {!compact && <span className="wordmark__sub">FIELD OPERATIONS · 48850</span>}
      </span>
    </span>
  );
}
