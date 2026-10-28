import { useMemo } from "react";

function hashAddress(address: string): number {
  let hash = 0;
  for (let index = 0; index < address.length; index += 1) {
    hash = (hash * 31 + address.charCodeAt(index)) >>> 0;
  }
  return hash;
}

export function Identicon({
  address,
  size = 28,
}: {
  address?: string | null;
  size?: number;
}) {
  const style = useMemo(() => {
    if (!address) return { background: "#2a2620" };
    const hash = hashAddress(address.toLowerCase());
    const hue = hash % 360;
    const hue2 = (hue + 43 + (hash % 50)) % 360;
    return {
      background: `conic-gradient(from ${hash % 360}deg at 50% 50%, hsl(${hue} 52% 52%), hsl(${hue2} 48% 38%), hsl(${hue} 40% 24%), hsl(${hue2} 52% 52%))`,
    };
  }, [address]);

  return (
    <span
      className="identicon"
      style={{ ...style, width: size, height: size }}
      aria-hidden="true"
    >
      <span className="identicon__inner" />
    </span>
  );
}
