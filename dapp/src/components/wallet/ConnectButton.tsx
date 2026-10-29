import { useState } from "react";
import { Wallet } from "lucide-react";
import { useAccount } from "wagmi";
import { AccountMenu } from "./AccountMenu";
import { ConnectDialog } from "./ConnectDialog";
import { useI18n } from "../../lib/i18n";
import { Button, type ButtonSize, type ButtonVariant } from "../ui/Button";

interface ConnectButtonProps {
  label?: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  className?: string;
}

export function ConnectButton({
  label,
  variant = "primary",
  size = "md",
  block = false,
  className,
}: ConnectButtonProps) {
  const { isConnected } = useAccount();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const text = label ?? t("Connect wallet", "连接钱包");

  if (isConnected) return <AccountMenu />;

  return (
    <>
      <Button
        variant={variant}
        size={size}
        block={block}
        className={className}
        iconLeft={<Wallet size={size === "sm" ? 13 : 15} />}
        onClick={() => setOpen(true)}
      >
        {text}
      </Button>
      <ConnectDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
