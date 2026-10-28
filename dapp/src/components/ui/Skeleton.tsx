interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: number;
}

export function Skeleton({ className = "", width, height = 14 }: SkeletonProps) {
  return (
    <span
      className={`skeleton ${className}`.trim()}
      style={{ width: width ?? "100%", height }}
      aria-hidden="true"
    />
  );
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <span className="skeleton-text" aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} width={index === lines - 1 ? "62%" : "100%"} height={12} />
      ))}
    </span>
  );
}

export function SkeletonCard() {
  return (
    <div className="skeleton-card" aria-hidden="true">
      <div className="skeleton-card__head">
        <Skeleton width={72} height={10} />
        <Skeleton width={52} height={20} />
      </div>
      <Skeleton width="70%" height={18} />
      <Skeleton width="45%" height={11} />
      <div className="skeleton-card__grid">
        <Skeleton height={38} />
        <Skeleton height={38} />
        <Skeleton height={38} />
      </div>
    </div>
  );
}
