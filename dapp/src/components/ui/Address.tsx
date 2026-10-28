import { Check, Copy, ExternalLink } from "lucide-react";
import { explorerAddressUrl, explorerTxUrl, shortAddr, shortHash } from "../../lib/format";
import { useCopy } from "../../lib/hooks";

interface CopyButtonProps {
  value: string;
  label?: string;
  className?: string;
}

export function CopyButton({ value, label = "复制", className = "" }: CopyButtonProps) {
  const [copied, copy] = useCopy();
  return (
    <button
      type="button"
      className={`copy-btn ${copied ? "is-copied" : ""} ${className}`.trim()}
      onClick={(event) => {
        event.stopPropagation();
        void copy(value);
      }}
      aria-label={copied ? "已复制" : label}
      title={copied ? "已复制" : label}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
    </button>
  );
}

type ValueKind = "address" | "tx" | "hash";

interface AddressChipProps {
  value?: string | null;
  kind?: ValueKind;
  label?: string;
  full?: boolean;
  copy?: boolean;
  link?: boolean;
  className?: string;
}

export function AddressChip({
  value,
  kind = "address",
  label,
  full = false,
  copy = true,
  link = true,
  className = "",
}: AddressChipProps) {
  if (!value) return <span className="addr addr--empty">—</span>;
  const url =
    link && kind === "address"
      ? explorerAddressUrl(value)
      : link && kind === "tx"
        ? explorerTxUrl(value)
        : null;
  const text = full ? value : kind === "address" ? shortAddr(value) : shortHash(value);

  return (
    <span className={`addr ${className}`.trim()}>
      {label && <span className="addr__label">{label}</span>}
      {url ? (
        <a
          className="addr__value mono"
          href={url}
          target="_blank"
          rel="noreferrer"
          title={value}
        >
          {text}
          <ExternalLink size={10} className="addr__external" aria-hidden="true" />
        </a>
      ) : (
        <span className="addr__value mono" title={value}>
          {text}
        </span>
      )}
      {copy && <CopyButton value={value} />}
    </span>
  );
}
